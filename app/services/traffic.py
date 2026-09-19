"""Deterministic traffic planning, EventBlock materialization, and as-run reconciliation."""
import re, uuid
from collections import defaultdict
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
from app.extensions import db
from app.models import (Advertiser,Campaign,CampaignScheduleRule,CommercialCreative,EventBlock,EventBlockItem,
    EventBlockItemExecution,ImagingAsset,Track,TrafficLog,TrafficPlacement,TrafficStopset,TrafficStopsetItem)
from app.services.event_blocks import validate_block
from app.services.schedule import _wall_to_utc
from app.services.stations import get_station

def clean(value,limit,required=False):
    value=''.join(c for c in (value or '').strip() if c.isprintable())
    if len(value)>limit or required and not value: raise ValueError(f'Enter at most {limit} characters')
    return value
def slug(value):
    value=re.sub('[^a-z0-9]+','-',(value or '').lower()).strip('-')
    if not value or len(value)>64: raise ValueError('Invalid slug')
    return value
def weekdays(value):
    try: days=sorted(set(int(x) for x in value if str(x).strip()))
    except (TypeError,ValueError): raise ValueError('Invalid weekdays')
    if not days or any(d<0 or d>6 for d in days): raise ValueError('Choose weekdays')
    return ','.join(map(str,days))
def dayset(value): return {int(x) for x in value.split(',')}
def station_for(code):
    row=get_station(code)
    if not row: raise ValueError('Station not found')
    return row

def create_advertiser(code,name,**values):
    s=station_for(code); row=Advertiser(station_id=s.id,name=clean(name,120,True),slug=slug(name),notes=clean(values.get('notes'),1000),external_reference=clean(values.get('external_reference'),80),contact_name=clean(values.get('contact_name'),120),contact_email=clean(values.get('contact_email'),254),contact_phone=clean(values.get('contact_phone'),40));db.session.add(row);db.session.commit();return row
def update_advertiser(row,name,**values):
    row.name=clean(name,120,True);row.external_reference=clean(values.get('external_reference'),80);row.contact_name=clean(values.get('contact_name'),120);row.contact_email=clean(values.get('contact_email'),254);row.contact_phone=clean(values.get('contact_phone'),40);row.notes=clean(values.get('notes'),1000);return row
def create_campaign(code,advertiser_slug,name,start_date,end_date,target=None,priority=100):
    s=station_for(code); advertiser=Advertiser.query.filter_by(station_id=s.id,slug=advertiser_slug).first()
    if not advertiser: raise ValueError('Advertiser belongs to another station or does not exist')
    if start_date>end_date: raise ValueError('Campaign start date must not follow end date')
    row=Campaign(station_id=s.id,advertiser_id=advertiser.id,name=clean(name,120,True),slug=slug(name),start_date=start_date,end_date=end_date,target_spot_count=target,priority=int(priority),status='DRAFT');db.session.add(row);db.session.commit();return row
def update_campaign(row,name,start_date,end_date,target=None,priority=100,notes=''):
    if start_date>end_date: raise ValueError('Campaign start date must not follow end date')
    row.name=clean(name,120,True);row.start_date=start_date;row.end_date=end_date;row.target_spot_count=int(target) if target not in (None,'') else None;row.priority=int(priority);row.notes=clean(notes,1000);return row
def attach_creative(campaign,asset_uuid,name,creative_code):
    asset=Track.query.filter_by(station_id=campaign.station_id,uuid=asset_uuid,deleted_at=None).first() or ImagingAsset.query.filter_by(station_id=campaign.station_id,uuid=asset_uuid).first()
    if not asset or asset.ingest_status!='accepted' or asset.decommissioned_at: raise ValueError('Creative audio is unavailable or cross-station')
    if (asset.audio_kind if isinstance(asset,Track) else asset.asset_type) not in ('COMMERCIALS','COMMERCIAL'): raise ValueError('Creative audio must use COMMERCIALS')
    row=CommercialCreative(station_id=campaign.station_id,campaign_id=campaign.id,track_id=asset.id if isinstance(asset,Track) else None,imaging_asset_id=asset.id if isinstance(asset,ImagingAsset) else None,name=clean(name,120,True),creative_code=clean(creative_code,40,True));db.session.add(row);db.session.commit();return row
def add_rule(campaign,days,start,end,target,minimum=0,maximum=None,priority=100):
    if start>=end: raise ValueError('Daypart start must precede end')
    row=CampaignScheduleRule(campaign_id=campaign.id,station_id=campaign.station_id,weekdays=weekdays(days),start_time=start,end_time=end,target_spots_per_day=int(target),minimum_separation_seconds=int(minimum),maximum_spots_per_day=maximum,priority=int(priority));db.session.add(row);db.session.commit();return row
def create_stopset(code,name,days,local_time,capacity,max_spots=None,timing_mode='SOFT'):
    s=station_for(code)
    if timing_mode not in ('SOFT','HARD','NON_INTERRUPTING') or int(capacity)<=0: raise ValueError('Invalid stopset settings')
    row=TrafficStopset(station_id=s.id,name=clean(name,120,True),slug=slug(name),weekdays=weekdays(days),local_time=local_time,capacity_seconds=int(capacity),max_spots=max_spots,timing_mode=timing_mode);db.session.add(row);db.session.commit();return row
def add_template_item(stopset,item_type,asset_uuid=None):
    if item_type=='FIXED_AUDIO':
        asset=Track.query.filter_by(station_id=stopset.station_id,uuid=asset_uuid,enabled=True,ingest_status='accepted',deleted_at=None,decommissioned_at=None).first()
        if not asset: raise ValueError('Fixed audio is unavailable or cross-station')
    elif item_type=='FIXED_IMAGING':
        asset=ImagingAsset.query.filter_by(station_id=stopset.station_id,uuid=asset_uuid,enabled=True,ingest_status='accepted').first()
        if not asset: raise ValueError('Fixed imaging is unavailable or cross-station')
    elif item_type=='COMMERCIAL_SLOT': asset=None
    else: raise ValueError('Unsupported stopset item type')
    row=TrafficStopsetItem(stopset=stopset,position=len(stopset.template_items)+1,item_type=item_type,track_id=asset.id if isinstance(asset,Track) else None,imaging_asset_id=asset.id if isinstance(asset,ImagingAsset) else None);db.session.add(row);db.session.commit();return row

def _instant(station,date,at): return _wall_to_utc(datetime.combine(date,at),ZoneInfo(station.timezone))
def generate_log(code,date):
    station=station_for(code); log=TrafficLog.query.filter_by(station_id=station.id,log_date=date).first()
    if log and log.status in ('FINALIZED','RECONCILED'): raise ValueError('Finalized traffic logs are immutable')
    if not log: log=TrafficLog(station_id=station.id,log_date=date,status='DRAFT');db.session.add(log);db.session.flush()
    TrafficPlacement.query.filter_by(traffic_log_id=log.id).delete();db.session.flush()
    stops=[s for s in TrafficStopset.query.filter_by(station_id=station.id,enabled=True).all() if date.weekday() in dayset(s.weekdays)]
    stops.sort(key=lambda s:(s.local_time,s.id)); used=defaultdict(int); last={}; report=[]
    campaigns=Campaign.query.filter(Campaign.station_id==station.id,Campaign.enabled.is_(True),Campaign.status=='ACTIVE',Campaign.start_date<=date,Campaign.end_date>=date).order_by(Campaign.priority.desc(),Campaign.id).all()
    for campaign in campaigns:
        rules=[r for r in campaign.rules if r.enabled and date.weekday() in dayset(r.weekdays)]
        requested=sum(min(r.target_spots_per_day,r.maximum_spots_per_day or r.target_spots_per_day) for r in rules); scheduled=0
        creatives=[c for c in campaign.creatives if c.enabled and c.audio.enabled and (not c.start_date or c.start_date<=date) and (not c.end_date or c.end_date>=date)]
        creatives.sort(key=lambda c:(TrafficPlacement.query.filter_by(commercial_creative_id=c.id,status='AIRED').count(),c.id))
        candidates=[]
        for rule in sorted(rules,key=lambda r:(-r.priority,r.id)):
            candidates += [(s,rule) for s in stops if rule.start_time<=s.local_time<rule.end_time]
        # Even deterministic spread: select candidates nearest equal target indices.
        if requested and candidates:
            picks=sorted(set(round(i*(len(candidates)-1)/max(1,requested-1)) for i in range(requested)))
            candidates=[candidates[i] for i in picks]+[c for i,c in enumerate(candidates) if i not in picks]
        for stop,rule in candidates:
            if scheduled>=requested or not creatives or used[(stop.id,'campaign',campaign.id)]: continue
            existing=TrafficPlacement.query.filter_by(traffic_log_id=log.id,traffic_stopset_id=stop.id).all()
            if stop.max_spots and len(existing)>=stop.max_spots: continue
            creative=creatives[scheduled%len(creatives)]; duration=creative.audio.duration_ms/1000
            fixed=sum(i.audio.duration_ms/1000 for i in stop.template_items if i.audio)
            placed=sum(p.creative.audio.duration_ms/1000 for p in existing)
            when=_instant(station,date,stop.local_time)
            prior=last.get(campaign.id)
            if prior and (when-prior).total_seconds()<rule.minimum_separation_seconds: continue
            if fixed+placed+duration>stop.capacity_seconds: continue
            slots=sum(i.item_type=='COMMERCIAL_SLOT' for i in stop.template_items)
            if not slots or len(existing)>=slots: continue
            row=TrafficPlacement(traffic_log_id=log.id,station_id=station.id,traffic_stopset_id=stop.id,scheduled_for_utc=when,campaign_id=campaign.id,commercial_creative_id=creative.id,position=len(existing)+1,status='PLANNED',advertiser_name=campaign.advertiser.name,campaign_name=campaign.name,creative_name=creative.name,creative_code=creative.creative_code)
            db.session.add(row);used[(stop.id,'campaign',campaign.id)]=1;last[campaign.id]=when;scheduled+=1
        report.append({'campaign':campaign.name,'requested':requested,'scheduled':scheduled,'unscheduled':requested-scheduled})
    log.status='GENERATED';log.generated_at=datetime.now(timezone.utc);db.session.commit();return log,report

def finalize_log(log):
    if log.status!='GENERATED': raise ValueError('Generate the draft before finalizing')
    from app.services.timed_events import save_event
    by_stop=defaultdict(list)
    for p in log.placements:
        if p.status!='CANCELLED': by_stop[p.stopset].append(p)
    for stop,placements in by_stop.items():
        block=EventBlock(station_id=log.station_id,name=f'{stop.name} {log.log_date}',slug=f'traffic-{log.log_date}-{stop.slug}',description='Finalized traffic materialization',block_type='STOPSET',enabled=True,failure_policy='SKIP_FAILED_ITEM');db.session.add(block);db.session.flush(); pi=iter(sorted(placements,key=lambda p:p.position));position=0
        for template in stop.template_items:
            creative=next(pi,None) if template.item_type=='COMMERCIAL_SLOT' else None
            asset=template.audio if template.item_type in ('FIXED_IMAGING','FIXED_AUDIO') else creative.creative.audio if creative else None
            if not asset: continue
            position+=1;item=EventBlockItem(event_block_id=block.id,position=position,item_type='TRACK' if isinstance(asset,Track) else 'IMAGING_ASSET',track_id=asset.id if isinstance(asset,Track) else None,imaging_asset_id=asset.id if isinstance(asset,ImagingAsset) else None,enabled=True,label=creative.creative_name if creative else getattr(asset,'title',None) or asset.name);db.session.add(item);db.session.flush()
            if creative: creative.event_block_item_id=item.id;creative.status='MATERIALIZED'
        if validate_block(block): raise ValueError('Materialized stopset is invalid')
        save_event(log.station.slug,name=f'Traffic: {stop.name}',timing_mode=stop.timing_mode,recurrence_type='ONE_TIME',content_type='EVENT_BLOCK',content_identifier=block.slug,local_date=log.log_date.isoformat(),local_time=stop.local_time.isoformat(),late_tolerance_seconds=300,missed_policy='SKIP',interrupt_policy='NEVER',priority=200)
    log.status='FINALIZED';log.finalized_at=datetime.now(timezone.utc);db.session.commit();return log

def reconcile_placement(item_execution):
    placement=TrafficPlacement.query.filter_by(event_block_item_id=item_execution.event_block_item_id).first()
    if placement:
        placement.event_block_execution_id=item_execution.block_execution_id;placement.event_block_item_execution_id=item_execution.id;placement.status='AIRED';placement.confirmed_started_at=item_execution.started_at
    return placement

def placement_queued(item_execution):
    placement=TrafficPlacement.query.filter_by(event_block_item_id=item_execution.event_block_item_id).first()
    if placement and placement.status=='MATERIALIZED':
        placement.status='QUEUED';placement.event_block_execution_id=item_execution.block_execution_id;placement.event_block_item_execution_id=item_execution.id
    return placement

def reconcile_log(log):
    for p in log.placements:
        if p.status in ('MATERIALIZED','QUEUED') and p.event_block_item_id:
            item=EventBlockItemExecution.query.filter_by(event_block_item_id=p.event_block_item_id).order_by(EventBlockItemExecution.id.desc()).first()
            if item and item.state in ('FAILED','SKIPPED'): p.status='MISSED' if item.state=='SKIPPED' else 'FAILED';p.failure_reason=item.failure_reason
    if all(p.status in ('AIRED','MISSED','FAILED','CANCELLED') for p in log.placements): log.status='RECONCILED';log.reconciled_at=datetime.now(timezone.utc)
    db.session.commit();return log

def _editable(log):
    if log.status not in ('DRAFT','GENERATED'): raise ValueError('Finalized traffic logs are immutable')

def _stop_capacity(log,stopset,exclude=None):
    rows=[p for p in log.placements if p.traffic_stopset_id==stopset.id and p.id!=(exclude.id if exclude else None) and p.status!='CANCELLED']
    fixed=sum(i.audio.duration_ms for i in stopset.template_items if i.audio)/1000
    used=sum(p.creative.audio.duration_ms for p in rows)/1000
    return rows,fixed+used

def _validate_draft_placement(log,stopset,creative,exclude=None):
    _editable(log)
    if stopset.station_id!=log.station_id or creative.station_id!=log.station_id: raise ValueError('Traffic resource belongs to another station')
    if log.log_date.weekday() not in dayset(stopset.weekdays) or not stopset.enabled: raise ValueError('Stopset is unavailable on this log date')
    campaign=creative.campaign
    if not campaign.enabled or campaign.status!='ACTIVE' or not campaign.start_date<=log.log_date<=campaign.end_date: raise ValueError('Campaign is not active on this log date')
    rules=[r for r in campaign.rules if r.enabled and log.log_date.weekday() in dayset(r.weekdays) and r.start_time<=stopset.local_time<r.end_time]
    if not rules: raise ValueError('Stopset is outside the campaign daypart')
    if not creative.enabled or not creative.audio.enabled or creative.audio.ingest_status!='accepted': raise ValueError('Creative is unavailable')
    rows,used=_stop_capacity(log,stopset,exclude)
    if any(p.campaign_id==campaign.id for p in rows): raise ValueError('Campaign already has a placement in this stopset')
    slots=sum(i.item_type=='COMMERCIAL_SLOT' for i in stopset.template_items)
    if len(rows)>=slots or stopset.max_spots and len(rows)>=stopset.max_spots: raise ValueError('Stopset has no remaining commercial inventory')
    if used+creative.audio.duration_ms/1000>stopset.capacity_seconds: raise ValueError('Placement does not fit stopset capacity')
    when=_instant(log.station,log.log_date,stopset.local_time)
    minimum=max(r.minimum_separation_seconds for r in rules)
    for p in log.placements:
        scheduled=p.scheduled_for_utc.replace(tzinfo=p.scheduled_for_utc.tzinfo or timezone.utc)
        target=when.replace(tzinfo=when.tzinfo or timezone.utc)
        if p.id!=(exclude.id if exclude else None) and p.campaign_id==campaign.id and p.status!='CANCELLED' and abs((scheduled-target).total_seconds())<minimum: raise ValueError('Placement violates campaign separation')
    return when

def _normalize_positions(log,stopset):
    rows=sorted((p for p in log.placements if p.traffic_stopset_id==stopset.id and p.status!='CANCELLED'),key=lambda p:(p.position,p.id))
    for n,p in enumerate(rows,1): p.position=100000+n
    db.session.flush()
    for n,p in enumerate(rows,1): p.position=n

def move_placement(placement,stopset):
    log=placement.traffic_log;when=_validate_draft_placement(log,stopset,placement.creative,placement);old=placement.stopset
    placement.traffic_stopset_id=stopset.id;placement.scheduled_for_utc=when;placement.position=100000;db.session.flush();_normalize_positions(log,old);_normalize_positions(log,stopset);return placement

def change_placement_creative(placement,creative):
    if creative.campaign_id!=placement.campaign_id: raise ValueError('Creative must belong to the placement campaign')
    _validate_draft_placement(placement.traffic_log,placement.stopset,creative,placement);placement.commercial_creative_id=creative.id;placement.creative_name=creative.name;placement.creative_code=creative.creative_code;return placement

def cancel_placement(placement):
    _editable(placement.traffic_log);log=placement.traffic_log;stopset=placement.stopset;placement.status='CANCELLED';placement.position=100000+placement.id;db.session.flush();_normalize_positions(log,stopset);return placement

def reorder_placements(log,stopset,ordered_ids):
    _editable(log);rows=[p for p in log.placements if p.traffic_stopset_id==stopset.id and p.status!='CANCELLED']
    try: ids=[int(x) for x in ordered_ids]
    except (TypeError,ValueError): raise ValueError('Invalid placement order')
    if sorted(ids)!=sorted(p.id for p in rows): raise ValueError('Placement order does not match this stopset')
    mapping={p.id:p for p in rows}
    for n,pid in enumerate(ids,1): mapping[pid].position=100000+n
    db.session.flush()
    for n,pid in enumerate(ids,1): mapping[pid].position=n
    return [mapping[x] for x in ids]

def shift_placement(placement,direction):
    _editable(placement.traffic_log)
    rows=sorted((p for p in placement.traffic_log.placements if p.traffic_stopset_id==placement.traffic_stopset_id and p.status!='CANCELLED'),key=lambda p:(p.position,p.id))
    index=next((n for n,p in enumerate(rows) if p.id==placement.id),None);target=index+(-1 if direction=='up' else 1 if direction=='down' else 999999)
    if index is None or target<0 or target>=len(rows): raise ValueError('Placement cannot move in that direction')
    rows[index],rows[target]=rows[target],rows[index]
    return reorder_placements(placement.traffic_log,placement.stopset,[p.id for p in rows])

def create_makegood(original,target_log,stopset):
    if original.status not in ('MISSED','FAILED'): raise ValueError('Only missed or failed placements need a makegood')
    if target_log.station_id!=original.station_id or stopset.station_id!=original.station_id: raise ValueError('Makegood resource belongs to another station')
    when=_validate_draft_placement(target_log,stopset,original.creative);existing=[p for p in target_log.placements if p.traffic_stopset_id==stopset.id and p.status!='CANCELLED']
    row=TrafficPlacement(traffic_log_id=target_log.id,station_id=original.station_id,traffic_stopset_id=stopset.id,scheduled_for_utc=when,campaign_id=original.campaign_id,commercial_creative_id=original.commercial_creative_id,position=len(existing)+1,status='PLANNED',is_makegood=True,makegood_for_id=original.id,advertiser_name=original.advertiser_name,campaign_name=original.campaign_name,creative_name=original.creative_name,creative_code=original.creative_code);db.session.add(row);return row

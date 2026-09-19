from datetime import timezone
from zoneinfo import ZoneInfo
"""Authenticated traffic planning UI over the traffic service."""
import csv,io
from datetime import date,datetime
from flask import Blueprint,abort,flash,make_response,redirect,render_template,request,url_for
from app.extensions import db
from app.models import Track
from app.models import Advertiser,Campaign,CampaignScheduleRule,CommercialCreative,ImagingAsset,TrafficLog,TrafficPlacement,TrafficStopset
from app.routes.web import admin_stations,station_or_404
from app.services.admin_auth import admin_required,can_manage_traffic,current_admin,require_csrf
from app.services.admin_media import audit
from app.services.traffic import (add_rule,add_template_item,attach_creative,cancel_placement,change_placement_creative,
 create_advertiser,create_campaign,create_makegood,create_stopset,finalize_log,generate_log,move_placement,reorder_placements,shift_placement,
 update_advertiser,update_campaign)

admin_traffic_blueprint=Blueprint('admin_traffic',__name__)
def station_for(slug):
    s=station_or_404(slug,require_enabled=False)
    if not can_manage_traffic(current_admin(),s):abort(403)
    return s
def back(slug):return redirect(url_for('.page',slug=slug),code=303)
@admin_traffic_blueprint.get('/admin/stations/<slug>/traffic')
@admin_required
def page(slug):
    s=station_for(slug);logs=TrafficLog.query.filter_by(station_id=s.id).order_by(TrafficLog.log_date.desc()).limit(31).all();campaigns=Campaign.query.filter_by(station_id=s.id).order_by(Campaign.name).all()
    delivery={c.id:{'scheduled':TrafficPlacement.query.filter_by(campaign_id=c.id).filter(TrafficPlacement.status.in_(('PLANNED','MATERIALIZED','QUEUED','AIRED'))).count(),'aired':TrafficPlacement.query.filter_by(campaign_id=c.id,status='AIRED').count(),'missed':TrafficPlacement.query.filter_by(campaign_id=c.id,status='MISSED').count(),'makegoods':TrafficPlacement.query.filter_by(campaign_id=c.id,is_makegood=True).filter(TrafficPlacement.status!='AIRED').count()} for c in campaigns}
    return render_template('admin/traffic.html',stations=admin_stations(),selected=s,page='traffic',advertisers=Advertiser.query.filter_by(station_id=s.id).order_by(Advertiser.name).all(),campaigns=campaigns,delivery=delivery,stopsets=TrafficStopset.query.filter_by(station_id=s.id).order_by(TrafficStopset.local_time).all(),logs=logs,commercials=Track.query.filter_by(station_id=s.id,audio_kind='COMMERCIALS',ingest_status='accepted',decommissioned_at=None,deleted_at=None).all())
@admin_traffic_blueprint.get('/admin/stations/<slug>/traffic/logs/<log_date>')
@admin_required
def log_detail(slug,log_date):
    s=station_for(slug)
    try: day=date.fromisoformat(log_date)
    except ValueError: abort(404)
    log=TrafficLog.query.filter_by(station_id=s.id,log_date=day).first_or_404();editable=TrafficLog.query.filter_by(station_id=s.id).filter(TrafficLog.status.in_(('DRAFT','GENERATED'))).order_by(TrafficLog.log_date).all()
    return render_template('admin/traffic_log.html',stations=admin_stations(),selected=s,page='traffic',log=log,stopsets=TrafficStopset.query.filter_by(station_id=s.id,enabled=True).order_by(TrafficStopset.local_time).all(),editable_logs=editable)
@admin_traffic_blueprint.post('/admin/stations/<slug>/traffic/<action>')
@admin_required
def mutate(slug,action):
    s=station_for(slug);require_csrf()
    try:
        if action=='advertiser': row=create_advertiser(slug,request.form.get('name'));target=row.slug
        elif action=='advertiser-edit':
            row=Advertiser.query.filter_by(station_id=s.id,slug=request.form.get('advertiser')).first()
            if not row:raise ValueError('Advertiser not found')
            update_advertiser(row,request.form.get('name'),external_reference=request.form.get('external_reference'),contact_name=request.form.get('contact_name'),contact_email=request.form.get('contact_email'),contact_phone=request.form.get('contact_phone'),notes=request.form.get('notes'));target=row.slug
        elif action=='advertiser-state':
            row=Advertiser.query.filter_by(station_id=s.id,slug=request.form.get('advertiser')).first()
            if not row:raise ValueError('Advertiser not found')
            row.enabled=request.form.get('enabled')=='1';target=row.slug
        elif action=='campaign':
            row=create_campaign(slug,request.form.get('advertiser'),request.form.get('name'),date.fromisoformat(request.form.get('start_date')),date.fromisoformat(request.form.get('end_date')),int(request.form['target']) if request.form.get('target') else None,int(request.form.get('priority',100)));target=row.slug
        elif action=='creative':
            campaign=Campaign.query.filter_by(station_id=s.id,slug=request.form.get('campaign')).first()
            if not campaign:raise ValueError('Campaign not found')
            row=attach_creative(campaign,request.form.get('asset'),request.form.get('name'),request.form.get('creative_code'));target=str(row.id)
        elif action=='rule':
            campaign=Campaign.query.filter_by(station_id=s.id,slug=request.form.get('campaign')).first()
            if not campaign:raise ValueError('Campaign not found')
            row=add_rule(campaign,request.form.getlist('weekday'),datetime.strptime(request.form.get('start_time'),'%H:%M').time(),datetime.strptime(request.form.get('end_time'),'%H:%M').time(),int(request.form.get('target')),int(request.form.get('minimum',0)));target=str(row.id)
        elif action=='campaign-status':
            row=Campaign.query.filter_by(station_id=s.id,slug=request.form.get('campaign')).first();status=request.form.get('status')
            if not row or status not in ('DRAFT','ACTIVE','PAUSED','COMPLETED','CANCELLED'):raise ValueError('Invalid campaign status')
            row.status=status;target=row.slug
        elif action=='campaign-edit':
            row=Campaign.query.filter_by(station_id=s.id,slug=request.form.get('campaign')).first()
            if not row:raise ValueError('Campaign not found')
            update_campaign(row,request.form.get('name'),date.fromisoformat(request.form.get('start_date')),date.fromisoformat(request.form.get('end_date')),request.form.get('target'),request.form.get('priority',100),request.form.get('notes'));target=row.slug
        elif action in ('creative-state','rule-state','stopset-state'):
            models={'creative-state':CommercialCreative,'rule-state':CampaignScheduleRule,'stopset-state':TrafficStopset};model=models[action]
            row=model.query.filter_by(station_id=s.id,id=int(request.form.get('id'))).first()
            if not row:raise ValueError('Traffic resource not found')
            row.enabled=request.form.get('enabled')=='1';target=str(row.id)
        elif action=='stopset':
            row=create_stopset(slug,request.form.get('name'),request.form.getlist('weekday'),datetime.strptime(request.form.get('local_time'),'%H:%M').time(),int(request.form.get('capacity')),int(request.form['max_spots']) if request.form.get('max_spots') else None,request.form.get('timing_mode'));target=row.slug
        elif action=='slot':
            stop=TrafficStopset.query.filter_by(station_id=s.id,slug=request.form.get('stopset')).first()
            if not stop:raise ValueError('Stopset not found')
            row=add_template_item(stop,request.form.get('item_type'),request.form.get('asset'));target=str(row.id)
        elif action=='generate': row,report=generate_log(slug,date.fromisoformat(request.form.get('log_date')));target=str(row.log_date)
        elif action=='finalize':
            row=TrafficLog.query.filter_by(station_id=s.id,id=int(request.form.get('log_id'))).first()
            if not row:raise ValueError('Traffic log not found')
            if request.form.get('confirm')!=row.log_date.isoformat():raise ValueError('Enter the log date to finalize')
            finalize_log(row);target=str(row.log_date)
        elif action=='makegood':
            original=TrafficPlacement.query.filter_by(id=int(request.form.get('placement_id')),station_id=s.id).first();stop=TrafficStopset.query.filter_by(slug=request.form.get('stopset'),station_id=s.id).first();target_log=TrafficLog.query.filter_by(id=int(request.form.get('target_log_id')),station_id=s.id).first()
            if not original or not stop or not target_log:raise ValueError('Placement, log, or stopset not found')
            row=create_makegood(original,target_log,stop);target=str(row.id)
        elif action in ('placement-move','placement-creative','placement-cancel'):
            placement=TrafficPlacement.query.filter_by(id=int(request.form.get('placement_id')),station_id=s.id).first()
            if not placement:raise ValueError('Placement not found')
            if action=='placement-move':
                stop=TrafficStopset.query.filter_by(slug=request.form.get('stopset'),station_id=s.id).first()
                if not stop:raise ValueError('Stopset not found')
                row=move_placement(placement,stop)
            elif action=='placement-creative':
                creative=CommercialCreative.query.filter_by(id=int(request.form.get('creative_id')),station_id=s.id).first()
                if not creative:raise ValueError('Creative not found')
                row=change_placement_creative(placement,creative)
            else: row=cancel_placement(placement)
            target=str(row.id)
        elif action=='placement-reorder':
            log=TrafficLog.query.filter_by(id=int(request.form.get('log_id')),station_id=s.id).first();stop=TrafficStopset.query.filter_by(slug=request.form.get('stopset'),station_id=s.id).first()
            if not log or not stop:raise ValueError('Log or stopset not found')
            reorder_placements(log,stop,request.form.getlist('placement_id'));target=str(log.id)
        elif action=='placement-shift':
            row=TrafficPlacement.query.filter_by(id=int(request.form.get('placement_id')),station_id=s.id).first()
            if not row:raise ValueError('Placement not found')
            shift_placement(row,request.form.get('direction'));target=str(row.id)
        else:abort(404)
        audit(f'traffic_{action}',user_id=current_admin().id,station_id=s.id,target_type='traffic',target_id=target,summary=f'Traffic {action} completed');db.session.commit();flash('Traffic operation completed.','success')
    except (ValueError,TypeError) as error:db.session.rollback();flash(str(error),'error')
    return back(slug)
@admin_traffic_blueprint.get('/admin/stations/<slug>/traffic/logs/<log_date>/as-run.csv')
@admin_required
def csv_report(slug,log_date):
    s=station_for(slug);log=TrafficLog.query.filter_by(station_id=s.id,log_date=date.fromisoformat(log_date)).first_or_404();out=io.StringIO();w=csv.writer(out);w.writerow(['Date','Scheduled UTC','Actual UTC','Advertiser','Campaign','Creative','Cart Code','Duration Seconds','Status','Makegood For'])
    for p in sorted(log.placements,key=lambda x:(x.scheduled_for_utc,x.position)):w.writerow([log.log_date,p.scheduled_for_utc.replace(tzinfo=p.scheduled_for_utc.tzinfo or timezone.utc).astimezone(ZoneInfo(s.timezone)).isoformat(),p.confirmed_started_at.replace(tzinfo=p.confirmed_started_at.tzinfo or timezone.utc).astimezone(ZoneInfo(s.timezone)).isoformat() if p.confirmed_started_at else '',p.advertiser_name,p.campaign_name,p.creative_name,p.creative.audio.cart_code or '',round(p.creative.audio.duration_ms/1000,3),p.status,p.makegood_for_id or ''])
    response=make_response(out.getvalue());response.headers['Content-Type']='text/csv; charset=utf-8';response.headers['Content-Disposition']=f'attachment; filename="traffic-{log.log_date}.csv"';return response

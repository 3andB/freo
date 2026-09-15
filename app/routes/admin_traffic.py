"""Authenticated traffic planning UI over the traffic service."""
import csv,io
from datetime import date,datetime
from flask import Blueprint,abort,flash,make_response,redirect,render_template,request,url_for
from app.extensions import db
from app.models import Advertiser,Campaign,CommercialCreative,ImagingAsset,TrafficLog,TrafficPlacement,TrafficStopset
from app.routes.web import admin_stations,station_or_404
from app.services.admin_auth import admin_required,can_manage_traffic,current_admin,require_csrf
from app.services.admin_media import audit
from app.services.traffic import add_rule,add_template_item,attach_creative,create_advertiser,create_campaign,create_makegood,create_stopset,finalize_log,generate_log

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
    return render_template('admin/traffic.html',stations=admin_stations(),selected=s,page='traffic',advertisers=Advertiser.query.filter_by(station_id=s.id).order_by(Advertiser.name).all(),campaigns=campaigns,delivery=delivery,stopsets=TrafficStopset.query.filter_by(station_id=s.id).order_by(TrafficStopset.local_time).all(),logs=logs,commercials=ImagingAsset.query.filter_by(station_id=s.id,asset_type='COMMERCIAL',ingest_status='accepted',decommissioned_at=None).all())
@admin_traffic_blueprint.post('/admin/stations/<slug>/traffic/<action>')
@admin_required
def mutate(slug,action):
    s=station_for(slug);require_csrf()
    try:
        if action=='advertiser': row=create_advertiser(slug,request.form.get('name'));target=row.slug
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
            from app.models import TrafficPlacement
            original=TrafficPlacement.query.filter_by(id=int(request.form.get('placement_id')),station_id=s.id).first();stop=TrafficStopset.query.filter_by(slug=request.form.get('stopset'),station_id=s.id).first()
            if not original or not stop:raise ValueError('Placement or stopset not found')
            row=create_makegood(original,stop);target=str(row.id)
        else:abort(404)
        audit(f'traffic_{action}',user_id=current_admin().id,station_id=s.id,target_type='traffic',target_id=target,summary=f'Traffic {action} completed');db.session.commit();flash('Traffic operation completed.','success')
    except (ValueError,TypeError) as error:db.session.rollback();flash(str(error),'error')
    return back(slug)
@admin_traffic_blueprint.get('/admin/stations/<slug>/traffic/logs/<log_date>/as-run.csv')
@admin_required
def csv_report(slug,log_date):
    s=station_for(slug);log=TrafficLog.query.filter_by(station_id=s.id,log_date=date.fromisoformat(log_date)).first_or_404();out=io.StringIO();w=csv.writer(out);w.writerow(['Date','Scheduled UTC','Actual UTC','Advertiser','Campaign','Creative','Cart Code','Duration Seconds','Status','Makegood For'])
    for p in sorted(log.placements,key=lambda x:(x.scheduled_for_utc,x.position)):w.writerow([log.log_date,p.scheduled_for_utc.isoformat(),p.confirmed_started_at.isoformat() if p.confirmed_started_at else '',p.advertiser_name,p.campaign_name,p.creative_name,p.creative.imaging_asset.cart_code or '',round(p.creative.imaging_asset.duration_ms/1000,3),p.status,p.makegood_for_id or ''])
    response=make_response(out.getvalue());response.headers['Content-Type']='text/csv; charset=utf-8';response.headers['Content-Disposition']=f'attachment; filename="traffic-{log.log_date}.csv"';return response

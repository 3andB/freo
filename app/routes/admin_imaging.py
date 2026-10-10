"""Compatibility redirects for retired Imaging bookmarks; no Imaging writes."""
from flask import Blueprint, abort, redirect, url_for
from app.models import Track, ImagingAsset
from app.routes.web import station_or_404
from app.services.admin_auth import admin_required
admin_imaging_blueprint=Blueprint('admin_imaging',__name__)

@admin_imaging_blueprint.get('/admin/stations/<slug>/imaging')
@admin_required
def library(slug):
    station_or_404(slug,require_enabled=False)
    return redirect(url_for('playlists.page',slug=slug),code=302)

@admin_imaging_blueprint.get('/admin/stations/<slug>/imaging/<path:legacy>')
@admin_required
def legacy(slug,legacy):
    station=station_or_404(slug,require_enabled=False)
    asset=ImagingAsset.query.filter_by(station_id=station.id,uuid=legacy.split('/')[-1]).first()
    track=Track.query.filter_by(station_id=station.id,legacy_imaging_id=asset.id).first() if asset else None
    if track:return redirect(url_for('admin_media.track_detail',slug=slug,track_uuid=track.uuid),code=302)
    return redirect(url_for('playlists.page',slug=slug),code=302)

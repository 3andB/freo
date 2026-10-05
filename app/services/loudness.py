"""One gain policy for playout and private previews; originals are untouched."""
import math

TARGET_LUFS = -16.0
TRUE_PEAK_CEILING = -1.5
MAX_BOOST_DB = 12.0


def gain_for(song, station=None):
    station = station or song.station
    target = station.target_lufs if station.target_lufs is not None else TARGET_LUFS
    measured, peak = song.loudness_lufs, song.true_peak_db
    from app.services.track_audio import effective
    trim = effective(song)['gain_trim_db'] if getattr(song, 'audio_edit_enabled', False) else 0
    if song.analysis_status != 'complete' or any(x is None or not math.isfinite(x) for x in (measured, peak)):
        gain = min(0, trim)
        return dict(target=target, db=gain, factor=10 ** (gain/20), status='Needs analysis', output_lufs=None,
                    normalization_db=0, requested_trim_db=trim, max_gain_db=0)
    desired = target - measured
    gain = min(desired, TRUE_PEAK_CEILING - peak, MAX_BOOST_DB)
    gain = max(-60.0, gain)
    normalization = gain
    requested = gain + trim
    gain = max(-60.0, min(requested, TRUE_PEAK_CEILING - peak, MAX_BOOST_DB))
    return dict(target=target, db=round(gain,3), factor=10 ** (gain/20),
                normalization_db=normalization, requested_trim_db=trim,
                max_gain_db=min(TRUE_PEAK_CEILING-peak, MAX_BOOST_DB),
                status=('Peak limited' if TRUE_PEAK_CEILING-peak <= MAX_BOOST_DB else 'Gain limited') if gain < (requested if trim else desired) - .05 else 'Trimmed' if trim else 'Normalized',
                output_lufs=round(measured + gain,1))

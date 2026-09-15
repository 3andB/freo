"""One gain policy for playout and private previews; originals are untouched."""
import math

TARGET_LUFS = -16.0
TRUE_PEAK_CEILING = -1.5
MAX_BOOST_DB = 12.0


def gain_for(song, station=None):
    station = station or song.station
    target = station.target_lufs if station.target_lufs is not None else TARGET_LUFS
    measured, peak = song.loudness_lufs, song.true_peak_db
    if song.analysis_status != 'complete' or any(x is None or not math.isfinite(x) for x in (measured, peak)):
        return dict(target=target, db=0.0, factor=1.0, status='Needs analysis', output_lufs=None)
    desired = target - measured
    gain = min(desired, TRUE_PEAK_CEILING - peak, MAX_BOOST_DB)
    gain = max(-60.0, gain)
    return dict(target=target, db=round(gain,3), factor=10 ** (gain/20),
                status=('Peak limited' if TRUE_PEAK_CEILING-peak <= MAX_BOOST_DB else 'Gain limited') if gain < desired - .05 else 'Normalized',
                output_lufs=round(measured + gain,1))

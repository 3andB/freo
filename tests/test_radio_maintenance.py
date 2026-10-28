"""Real file safety for staged native engine activation."""
import pytest
from freo_ops import radio_maintenance as radio, recovery


def staging(tmp_path):
    target=tmp_path/'station.liq';target.write_text('old')
    pending=tmp_path/'.station.staged';pending.write_text('new');pending.chmod(0o640)
    return target,pending,{str(target):dict(temporary=str(pending),before_sha256=recovery.digest(target))}


def test_native_activation_preserves_validated_permissions(tmp_path):
    target,pending,changes=staging(tmp_path)
    radio.apply(changes)
    assert target.read_text()=='new' and not pending.exists()
    assert target.stat().st_mode&0o777==0o640


@pytest.mark.parametrize('interference',['content','symlink'])
def test_native_activation_rejects_every_changed_source_before_any_replacement(tmp_path,interference):
    target,pending,changes=staging(tmp_path)
    extra=tmp_path/'second.liq';extra.write_text('second')
    second=tmp_path/'.second.staged';second.write_text('new second')
    changes[str(extra)]=dict(temporary=str(second),before_sha256=recovery.digest(extra))
    if interference=='content':extra.write_text('edited')
    else:
        extra.unlink();extra.symlink_to(target)
    with pytest.raises(recovery.RecoveryError,match='changed during maintenance'):radio.apply(changes)
    assert target.read_text()=='old' and pending.exists()
    radio.discard(changes)
    assert not pending.exists() and not second.exists()

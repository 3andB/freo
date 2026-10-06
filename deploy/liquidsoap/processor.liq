# One immutable parameter list is replaced per validated command.
processor_values = ref(__PROCESSOR_INITIAL__)
def pv(n) = list.nth(default=0.0, processor_values(), n) end
processor_dry = radio
processor_enabled = {pv(0) > 0.0 or pv(1) > 0.0 or pv(2) > 0.0}
processor_failed = ref(false)
processor_wet = error.catch(errors=null(), fun () -> begin
  agc = normalize(target={pv(3)}, lufs=true, gain_min=-6.0, gain_max=6.0, threshold=-40.0,
    up=10.0, down=0.5, window=3.0, lookahead=0.0, track_sensitive=false, processor_dry)
  processed = switch(track_sensitive=false, [({pv(0) > 0.0}, agc), ({true}, processor_dry)])
  processed = filter.iir.eq.peak(frequency=100.0, gain={if pv(2)>0.0 then pv(5) else 0.0 end}, q=0.7, processed)
  processed = filter.iir.eq.peak(frequency=1000.0, gain={if pv(2)>0.0 then pv(6) else 0.0 end}, q=0.7, processed)
  processed = filter.iir.eq.peak(frequency=8000.0, gain={if pv(2)>0.0 then pv(7) else 0.0 end}, q=0.7, processed)
  compress.multiband(limit=false, wet={pv(1)}, processed, [
    {frequency=200.0, attack=20.0, release=250.0, ratio={pv(4)}, threshold=-18.0, gain=0.0},
    {frequency=2500.0, attack=20.0, release=250.0, ratio={pv(4)}, threshold=-18.0, gain=0.0},
    {frequency=22050.0, attack=20.0, release=250.0, ratio={pv(4)}, threshold=-18.0, gain=0.0}
  ])
end, fun (_) -> begin processor_failed := true; processor_dry end)
server.register(namespace="freo_processor", "state", fun (_) -> if processor_failed() then "BYPASS" else "READY" end)
server.register(namespace="freo_processor", "apply", fun (value) -> begin
  values = list.map(fun (v) -> float_of_string(default=999.0,v), string.split(separator=" ",value))
  def at(n) = list.nth(default=999.0,values,n) end
  if list.length(values) != 8 or at(0)<0.0 or at(0)>1.0 or at(1)<0.0 or at(1)>1.0 or at(2)<0.0 or at(2)>1.0 or
    at(3)< -22.0 or at(3)> -12.0 or at(4)<1.0 or at(4)>3.0 or
    at(5)< -6.0 or at(5)>6.0 or at(6)< -6.0 or at(6)>6.0 or at(7)< -6.0 or at(7)>6.0 then "ERROR invalid processor"
  elsif processor_failed() then "ERROR processor bypassed"
  else processor_values := values; "OK" end
end)
# Fallible processed source always has the original program behind it.
radio = fallback(track_sensitive=false, [switch(track_sensitive=false, [({processor_enabled() and not processor_failed()}, processor_wet)]), processor_dry])

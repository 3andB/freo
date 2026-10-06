# Bulletin uses the existing event reservation and main-program priority rules.
bulletin_id = ref("")
bulletin_phase = ref("IDLE")
bulletin_kind = ref("FILE")
bulletin_duration = ref(180.0)
bulletin_began = ref(0.0)
bulletin_lease = ref(0.0)
bulletin_deadline = ref(0.0)
bulletin_intro = program_queue("freo_bulletin_intro")
bulletin_file = program_queue("freo_bulletin_file")
bulletin_outro = program_queue("freo_bulletin_outro")
bulletin_connected = ref(false)
bulletin_live = input.http(id="freo_bulletin_live", start=false, clock_safe=false, max_buffer=2.0,
  poll_delay=10.0, timeout=10.0,
  string_args=[("protocol_whitelist","http,tcp"),("format_whitelist","mp3,aac,ogg,flac,wav")],
  on_connect=fun (_) -> bulletin_connected := true,
  on_disconnect={bulletin_connected := false}, on_error=fun (_) -> bulletin_connected := false, "")
bulletin_live.log.level.set(0)
bulletin_noise = ref(false)
bulletin_live_audio = blank.detect(max_blank=3.0, min_noise=0.1, threshold=-55.0, start_blank=true,
  track_sensitive=false, on_noise={bulletin_noise := true}, {bulletin_noise := false}, bulletin_live)
output.dummy(id="freo_bulletin_drain", fallible=true, bulletin_live_audio)
def bulletin_ready()
  if bulletin_kind() == "LIVE" then bulletin_connected() and bulletin_live.is_ready() and bulletin_noise()
  else bulletin_file.is_ready() end
end
def bulletin_finish(phase)
  bulletin_phase := phase
  if event_token() == bulletin_id() then
    event_token := ""; event_playing := false
    event_wait_a := false; event_wait_b := false; event_wait_auto := false
  end
  bulletin_live.stop(); bulletin_connected := false
  bulletin_intro.set_queue([]); bulletin_outro.set_queue([]); bulletin_file.set_queue([])
  bulletin_intro.skip(); bulletin_outro.skip(); bulletin_file.skip()
end
def bulletin_body()
  if bulletin_ready() then bulletin_phase := "BODY"; bulletin_began := time()
  else bulletin_finish("FAILED") end
end
def bulletin_end()
  if bulletin_outro.is_ready() then bulletin_phase := "OUTRO" else bulletin_finish("COMPLETED") end
end
bulletin_intro.on_track(confirm)
bulletin_outro.on_track(confirm)
bulletin_intro_audio = source.on_end(delay=0.0, track_fades(bulletin_intro), fun (_,_) -> if bulletin_phase()=="INTRO" then bulletin_body() end)
bulletin_outro_audio = source.on_end(delay=0.0, track_fades(bulletin_outro), fun (_,_) -> if bulletin_phase()=="OUTRO" then bulletin_finish("COMPLETED") end)
bulletin_file_audio = source.on_end(delay=0.0, bulletin_file, fun (_,_) -> if bulletin_phase()=="BODY" then bulletin_end() end)
server.register(namespace="freo_bulletin", "prepare", fun (value) -> begin
  fields = string.split(separator="\\|",value)
  def field(n) = list.nth(default="",fields,n) end
  if field(0) == bulletin_id() then "OK"
  elsif event_token() != "" or (bulletin_phase() != "IDLE" and bulletin_phase() != "FAILED" and bulletin_phase() != "COMPLETED") then "ERROR event busy"
  else
    bulletin_finish("IDLE")
    bulletin_id := field(0); bulletin_kind := field(1)
    bulletin_duration := float_of_string(default=180.0,field(3)); bulletin_began := 0.0
    bulletin_lease := time()+15.0; bulletin_deadline := time()+bulletin_duration()+480.0
    def enqueue(source, uri)
      if uri != "-" then
        r = request.create(uri)
        if source.add(r) then true else request.destroy(r); false end
      else true end
    end
    error.catch(errors=null(), fun () -> begin
      intro_ok = enqueue(bulletin_intro,field(4))
      outro_ok = enqueue(bulletin_outro,field(5))
      body_ok = if bulletin_kind() == "LIVE" then
        bulletin_live.set_url(field(2)); bulletin_live.start(); true
      else enqueue(bulletin_file,field(2)) end
      if intro_ok and outro_ok and body_ok then bulletin_phase := "PREPARING"; "OK"
      else bulletin_finish("FAILED"); "ERROR unavailable bulletin" end
    end, fun (_) -> begin bulletin_finish("FAILED"); "ERROR unavailable bulletin" end)
  end
end)
server.register(namespace="freo_bulletin", "lease", fun (id) -> begin
  if id == bulletin_id() then bulletin_lease := time()+15.0 end; "OK"
end)
server.register(namespace="freo_bulletin", "cancel", fun (id) -> begin
  if id == bulletin_id() then bulletin_finish("FAILED") end; "OK"
end)
server.register(namespace="freo_bulletin", "state", fun (_) ->
  bulletin_id() ^ "|" ^ bulletin_phase() ^ "|" ^ string.float(bulletin_began()))
thread.run(every=0.05, fun () -> begin
  phase = bulletin_phase()
  if phase == "PREPARING" and bulletin_ready() then bulletin_phase := "READY" end
  if phase == "PREPARING" or phase == "READY" or phase == "INTRO" or phase == "BODY" or phase == "OUTRO" then
    if time()>bulletin_lease() or time()>bulletin_deadline() then bulletin_finish("FAILED")
    elsif event_token() == bulletin_id() and event_playing() then
      if mic_active() or (cart_takeover() and cart.is_ready()) or mode() != "AUTO" then bulletin_finish("FAILED")
      elsif phase == "READY" then
        if not bulletin_ready() then bulletin_finish("FAILED")
        elsif bulletin_intro.is_ready() then bulletin_phase := "INTRO"
        else bulletin_body() end
      elsif phase == "INTRO" and (not bulletin_ready() or not bulletin_intro.is_ready()) then bulletin_finish("FAILED")
      elsif phase == "OUTRO" and not bulletin_outro.is_ready() then bulletin_finish("FAILED")
      elsif phase == "BODY" then
        if not bulletin_ready() then bulletin_finish("FAILED")
        elsif time()-bulletin_began() >= bulletin_duration() then bulletin_end() end
      end
    end
  end
end)
bulletin_output = switch(track_sensitive=false, [
  ({event_playing() and event_token()==bulletin_id() and bulletin_phase()=="INTRO"}, amplify(override="freo_gain",1.0,bulletin_intro_audio)),
  ({event_playing() and event_token()==bulletin_id() and bulletin_phase()=="BODY" and bulletin_kind()=="FILE"}, bulletin_file_audio),
  ({event_playing() and event_token()==bulletin_id() and bulletin_phase()=="BODY" and bulletin_kind()=="LIVE"}, bulletin_live_audio),
  ({event_playing() and event_token()==bulletin_id() and bulletin_phase()=="OUTRO"}, amplify(override="freo_gain",1.0,bulletin_outro_audio))
])

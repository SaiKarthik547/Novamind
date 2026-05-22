extends CanvasLayer
class_name DiagnosticsOverlay

var stats_label: Label
var update_timer: float = 0.0
var ping_start: float = 0.0
var current_latency: float = 0.0
var dropped_events: int = 0

func _init():
	name = "DiagnosticsOverlay"
	layer = 100 # Always on top
	
	var margin = MarginContainer.new()
	margin.add_theme_constant_override("margin_top", 10)
	margin.add_theme_constant_override("margin_right", 10)
	margin.set_anchors_preset(Control.PRESET_TOP_RIGHT)
	add_child(margin)
	
	var panel = PanelContainer.new()
	var style = StyleBoxFlat.new()
	style.bg_color = Color(0, 0, 0, 0.7)
	style.set_corner_radius_all(5)
	panel.add_theme_stylebox_override("panel", style)
	margin.add_child(panel)
	
	stats_label = Label.new()
	stats_label.add_theme_font_size_override("font_size", 12)
	stats_label.add_theme_color_override("font_color", Color(0.2, 1.0, 0.4)) # Hacker green
	panel.add_child(stats_label)

func _process(delta):
	update_timer += delta
	if update_timer > 0.5: # Update twice a second
		_update_stats()
		update_timer = 0.0

func _update_stats():
	var fps = Engine.get_frames_per_second()
	var mem_static = OS.get_static_memory_usage() / 1048576.0 # MB
	
	var connection_status = "OFFLINE"
	var protocol = "UNKNOWN"
	
	# Try to fetch network state
	var net_mgr = get_node_or_null("/root/Main/NetworkManager")
	if net_mgr and net_mgr.socket:
		var state = net_mgr.socket.get_ready_state()
		if state == WebSocketPeer.STATE_OPEN:
			connection_status = "CONNECTED"
			protocol = "1.0.0" # Hardcoded expectation for now
			
	# Note: In a full implementation, we'd hook into VoxelTerrain chunk counts
	# and query Python for active agent queues.
	
	var text = "[ SYSTEM DIAGNOSTICS ]\n"
	text += "----------------------\n"
	text += "FPS:          %d\n" % fps
	text += "Memory:       %.1f MB\n" % mem_static
	text += "IPC Status:   %s\n" % connection_status
	text += "Protocol:     %s\n" % protocol
	text += "Latency:      %.1f ms\n" % current_latency
	text += "Dropped Pkts: %d\n" % dropped_events
	
	stats_label.text = text

func update_latency(ms: float):
	current_latency = ms

func record_dropped_packet():
	dropped_events += 1

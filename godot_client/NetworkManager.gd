extends Node

var socket = WebSocketPeer.new()
var url = "ws://127.0.0.1:8765"
var crypto = Crypto.new()

signal event_received(event_data)
signal state_updated(state_data)

func _ready():
	print("NetworkManager: Connecting to Bridge Server at ", url)
	var err = socket.connect_to_url(url)
	if err != OK:
		print("NetworkManager: Failed to initiate connection. Error: ", err)

func _process(_delta):
	socket.poll()
	var state = socket.get_ready_state()
	
	if state == WebSocketPeer.STATE_OPEN:
		while socket.get_available_packet_count() > 0:
			var packet = socket.get_packet()
			var message = packet.get_string_from_utf8()
			_handle_message(message)
			
	elif state == WebSocketPeer.STATE_CLOSED:
		var code = socket.get_close_code()
		var reason = socket.get_close_reason()
		print("NetworkManager: WebSocket Closed with code: %d, reason: %s. Attempting to reconnect..." % [code, reason])
		set_process(false)
		await get_tree().create_timer(3.0).timeout
		_reconnect()

func _reconnect():
	print("NetworkManager: Reconnecting...")
	socket.connect_to_url(url)
	set_process(true)

func _handle_message(message: String):
	var json = JSON.new()
	var error = json.parse(message)
	if error == OK:
		var data = json.data
		var msg_type = data.get("type", "UNKNOWN")
		var action = data.get("action", "")
		
		if msg_type == "HEARTBEAT":
			if action == "ping":
				send_message("HEARTBEAT", "pong")
			return
			
		print("Received %s: %s" % [msg_type, action])
		
		match msg_type:
			"EVENT":
				event_received.emit(data)
			"STATE_UPDATE":
				state_updated.emit(data)
			"COMMAND":
				_handle_command(data)
			"ERROR":
				print("Bridge Error: ", data.get("payload", {}))
	else:
		print("Failed to parse message: ", message)

func _handle_command(data: Dictionary):
	var action = data.get("action", "")
	var payload = data.get("payload", {})
	print("Executing Command: ", action, " with payload: ", payload)
	# TODO: Dispatch to appropriate Godot systems

func send_message(msg_type: String, action: String, payload: Dictionary = {}):
	var message = {
		"type": msg_type,
		"action": action,
		"payload": payload,
		"timestamp": Time.get_unix_time_from_system(),
		"msg_id": crypto.generate_random_bytes(16).hex_encode()
	}
	var json_str = JSON.stringify(message)
	if socket.get_ready_state() == WebSocketPeer.STATE_OPEN:
		socket.send_text(json_str)
	else:
		print("Cannot send message, socket is not open")

import copy
import json
import os
import threading
import time
from queue import Queue

import bluetooth

import utils

TOPOLOGY = set()
SOCKETS = {}
MESSAGES = {}
DISPLAY_NAME = os.environ['NETWORKS_USERNAME']

assert DISPLAY_NAME is not None


def start_client():
    global TOPOLOGY
    service_matches = bluetooth.find_service(name="NetworksTest")

    if len(service_matches) == 0:
        print("start_client: Couldn't find the NetworksTest service")
    else:
        for service in service_matches:
            port = service["port"]
            host = service["host"]
            display_name = service["description"]

            # Create the client socket
            if not display_name in SOCKETS:
                print("start_client: Connecting to \"%s\" port %s" % (display_name, port,))

                socket = bluetooth.BluetoothSocket(bluetooth.RFCOMM)

                try:
                    socket.connect((host, port))
                    socket.send(DISPLAY_NAME)
                except Exception as e:
                    continue

                socket.settimeout(5.0)
                SOCKETS[display_name] = socket
                TOPOLOGY.add(frozenset([DISPLAY_NAME, display_name]))

                threading.Thread(
                    target=receiver,
                    args=[socket, display_name]
                ).start()

                threading.Thread(
                    target=sender,
                    args=[socket, display_name]
                ).start()

                print("start_client: Connected to {} on port {}.".format(display_name, port))

# ============================================================================= #


def flood_control_message(event, target_user):
    for destination in utils.get_all_devices(TOPOLOGY, DISPLAY_NAME):
        new_msg = utils.control_message(event, target_user, DISPLAY_NAME)
        new_msg['destination'] = destination
        send_message(new_msg)


def send_message(msg_dict):
    # To be used for data messages
    # Appends the path, and puts it in the queue
    msg_dict['path'] = utils.get_path(msg_dict['source'], msg_dict['destination'], TOPOLOGY)
    print(msg_dict)
    msg_dict['path'].pop(0)
    next_hop = msg_dict['path'][0]
    MESSAGES[next_hop].put(msg_dict)


def update_topology(dictionary):
    global TOPOLOGY

    # If the entire message will be passed,
    # access set dictionary to dictionary['data']

    if(dictionary['event'] == 'connection'):
        TOPOLOGY.add(frozenset([dictionary['point1'], dictionary['point2']]))
    elif(dictionary['event'] == 'disconnection'):
        TOPOLOGY.remove(frozenset([dictionary['point1'], dictionary['point2']]))
    else:
        raise "Control event not recognized"


def receiver(client_socket, client_name):
    while True:
        try:
            data = client_socket.recv(1024).decode('utf-8')

            print(data)

            if data == "ping":
                continue

            # TODO: Handle routing
            msg = json.loads(data)
            if msg['destination'] == DISPLAY_NAME:
                # Message intended for me
                if msg['type'] == 'control':
                    update_topology(msg['data'])
                else:
                    # Data message
                    print(msg['source'], ': ', msg['data'])
            else:
                msg['path'].pop(0)
                MESSAGES[msg['path'][0]] = msg

        except Exception as e:
            # Timeout
            continue


def handle_disconnection(client_name):
    # Remove from topology
    # Flood disconnection
    TOPOLOGY.remove(frozenset([DISPLAY_NAME, client_name]))
    del SOCKETS[client_name]
    # TODO: Close the thread

    flood_control_message('disconnection', client_name)


def disconnection_detector():
    while True:
        for name, socket in SOCKETS.items():
            try:
                socket.send("ping")
            except Exception as e:
                handle_disconnection(name)
        time.sleep(5)


def sender(client_socket, name):
    while True:
        try:
            msg = MESSAGES[name].get()
            client_socket.send(json.dumps(msg))
        except Exception as e:
            pass


def start_server(port):
    server_sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
    server_sock.bind(("", port))
    server_sock.listen(port)

    bluetooth.advertise_service(
        server_sock, "NetworksTest", description=DISPLAY_NAME)

    print("start_server: Waiting for connections on RFCOMM channel %d" % port)

    while True:
        client_socket, client_info = server_sock.accept()
        print("start_server: Accepted connection from ", client_info)

        client_socket.settimeout(5.0)  # Will raise if 'recv' waits for more than 5s

        try:
            # First message will be the display name
            client_name = client_socket.recv(1024)
        except Exception as e:
            continue

        TOPOLOGY.add(frozenset([DISPLAY_NAME, client_name]))
        SOCKETS[client_name] = client_socket
        MESSAGES[client_name] = Queue()

        # Flood connection
        flood_control_message('connection', client_name)

        threading.Thread(
            target=receiver,
            args=[client_socket, client_name]

        ).start()

        threading.Thread(
            target=sender,
            args=[client_socket, client_name]
        ).start()


if __name__ == "__main__":
    threading.Thread(target=start_server, args=(1, )).start()
    threading.Thread(target=disconnection_detector).start()

    while True:
        time.sleep(5)
        start_client()

# {
#     'source': DISPLAY_NAME,
#     'destination': '',
#     'data': {},
#     'path': []
# }

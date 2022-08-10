import json
import os
import socket

import firebase_admin
import firebase_admin.storage as storage
from firebase_admin.firestore import client
from push_receiver import register, listen

from player import Player

SENDER_ID = int(os.environ.get("FIREBASE_SENDER_ID"))

player = None


def on_notification(obj, notification, data_message):
    print("message recieved")

    idstr = data_message.persistent_id + "\n"

    # check if we already received the notification
    with open("persistent_ids.txt", "r") as f:
        if idstr in f:
            return

    # new notification, store id so we don't read it again
    with open("persistent_ids.txt", "a") as f:
        f.write(idstr)

    data = notification.get("data", {})

    # print command to run
    command_to_run = data.get("command")

    if player:
        player.execute_command(command_to_run)


def get_or_create_room(firestore, token: str):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    client_url = s.getsockname()[0]
    ip_add = client_url.split(".")[-1]

    ref_id = f"player_{ip_add}"
    doc_ref = firestore.collection("rooms").document(ref_id)

    room_doc = doc_ref.get()

    if room_doc.exists:
        room_doc_data = room_doc.to_dict()

        if room_doc_data.get("token") != token:
            doc_ref.set({"token": token}, merge=True)
    else:
        doc_ref.set({"roomName": ref_id, "token": token})

    currently_playing_ref = doc_ref.collection("currently_playing").document("current")

    currently_playing_ref.set(
        {
            "playingRef": None,
            "thumbnailLink": None,
            "fileName": None,
            "isPaused": True,
            "isLoading": True,
        }
    )

    return (doc_ref, currently_playing_ref)


if __name__ == "__main__":
    try:
        # already registered, load previous credentials
        with open("credentials.json", "r") as f:
            credentials = json.load(f)
    except FileNotFoundError:
        # first time, register and store credentials
        credentials = register(sender_id=SENDER_ID)
        with open("credentials.json", "w") as f:
            json.dump(credentials, f)

    token = credentials["fcm"]["token"]

    cred_obj = firebase_admin.credentials.Certificate(
        "arcadeartbox-firebase-adminsdk-a221q-792a936e30.json"
    )
    default_app = firebase_admin.initialize_app(
        cred_obj, {"storageBucket": "arcadeartbox.appspot.com"}
    )

    firestore = client(app=default_app)

    (doc_ref, currently_playing_ref) = get_or_create_room(firestore, token)
    storage_bucket = storage.bucket()

    player = Player(firestore, currently_playing_ref, storage_bucket)

    with open("persistent_ids.txt", "a+") as f:
        received_persistent_ids = [x.strip() for x in f]

    listen(credentials, on_notification, received_persistent_ids)

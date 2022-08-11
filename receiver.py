import json
import os
import socket
import sys

import firebase_admin
import firebase_admin.storage as storage
from firebase_admin.firestore import client
from push_receiver import PushReceiver
from push_receiver.register import register

from player import Player

SENDER_ID = int(os.environ.get("FIREBASE_SENDER_ID"))
PATH_TO_CREDS = os.environ.get("FIREBASE_CREDS")
APP_ID = os.environ.get("FIREBASE_APP_ID")


class Receiver:
    def __init__(self, firestore, token: str) -> None:
        self.firestore = firestore
        self.token = token
        doc_ref, currently_playing_ref = self.get_or_create_room()
        storage_bucket = storage.bucket()

        player = Player(firestore, currently_playing_ref, storage_bucket)
        self.player = player

    def on_notification(self, obj, notification: dict, data_message):
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

        if self.player:
            self.player.execute_command(command_to_run)

    def get_or_create_room(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        client_url = s.getsockname()[0]
        ip_add = client_url.split(".")[-1]

        ref_id = f"player_{ip_add}"
        doc_ref = self.firestore.collection("rooms").document(ref_id)

        room_doc = doc_ref.get()

        if room_doc.exists:
            room_doc_data = room_doc.to_dict()

            if room_doc_data.get("token") != self.token:
                doc_ref.set({"token": self.token}, merge=True)
        else:
            doc_ref.set({"roomName": ref_id, "token": self.token})

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


def main():
    if not PATH_TO_CREDS or not SENDER_ID or not APP_ID:
        error = RuntimeError(
            "PATH_TO_CREDS, SENDER_ID, or APP_ID not set. Please check your environemnt variables."
        )
        raise error.with_traceback(sys.exc_info()[2])
    try:
        # already registered, load previous credentials
        with open("credentials.json", "r") as f:
            credentials = json.load(f)
    except FileNotFoundError:
        # first time, register and store credentials
        credentials = register(sender_id=SENDER_ID, app_id=APP_ID)
        with open("credentials.json", "w") as f:
            json.dump(credentials, f)

    token = credentials["fcm"]["token"]

    cred_obj = firebase_admin.credentials.Certificate(PATH_TO_CREDS)
    default_app = firebase_admin.initialize_app(
        cred_obj, {"storageBucket": "arcadeartbox.appspot.com"}
    )

    firestore = client(app=default_app)

    with open("persistent_ids.txt", "a+") as f:
        received_persistent_ids = [x.strip() for x in f]

    app_receiver = Receiver(firestore, token)

    receiver = PushReceiver(credentials, received_persistent_ids)
    receiver.listen(app_receiver.on_notification)


if __name__ == "__main__":
    main()

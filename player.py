import threading
import logging
from random import choice
from typing import Optional

from google.cloud.storage import Bucket
from google.cloud.firestore import Client
from omxplayer.player import OMXPlayer

logging.basicConfig(level=logging.INFO)
player_log = logging.getLogger("Player 1")

SERVER_URL = f"https://firebasestorage.googleapis.com/v0/b/arcadeartbox.appspot.com/o"

VOL_INCREMENT = 0.1
MAX_VOLUME = 1
SKIP_INCREMENT = 5


class Player:
    def __init__(
        self, firestore: Client, currently_playing_ref, storage_bucket: Bucket
    ):
        self.firestore = firestore
        self.storage_bucket = storage_bucket
        self.player: Optional[OMXPlayer] = None
        self.room_id = None
        self.end_volume = 1
        self.videos = {}
        self.currently_playing_ref = currently_playing_ref

        self.video_callback_done = threading.Event()

        col_query = self.firestore.collection("videos")

        # Watch the collection query
        col_query.on_snapshot(self.on_snapshot)

    def on_snapshot(self, col_snapshot: list, changes, read_time):
        self.videos = {snapshot.id: snapshot.to_dict() for snapshot in col_snapshot}

        if not self.player or self.player.is_playing:
            self.start_player()

        self.video_callback_done.set()

    def start_player(self):
        if self.videos:
            self.create_player()
            self.end_volume = self.player.volume()

    def create_player(self):
        player_log.info("Starting player...")
        random_video_id = choice(list(self.videos.keys()))
        random_video = self.videos[random_video_id]

        file_path = random_video["file_path"]
        file_blob = self.storage_bucket.get_blob(file_path)
        file_metadata: dict = file_blob.metadata
        file_token = file_metadata.get("firebaseStorageDownloadTokens")
        url = f"{SERVER_URL}/{file_path}?alt=media&token={file_token}"

        arg_string = f"-b --vol {self.end_volume}"

        self.player = OMXPlayer(url, args=arg_string)
        self.player.playEvent = self.on_play
        self.player.pauseEvent = self.on_pause
        self.player.exitEvent = self.refresh

        player_log.info("Player started.")

        self.currently_playing_ref.set(
            {
                "playingRef": f"videos/{random_video_id}",
                "thumbnailLink": random_video.get("thumbnail_path"),
                "fileName": file_path,
                "isPaused": False,
                "isLoading": False,
            }
        )

    def execute_command(self, action):
        player_log.info(f"Command recieved - {action}")
        if self.player:
            if action == "refresh":
                self.next()
            elif action == "pause":
                self.player.pause()
            elif action == "play":
                self.player.play()
            elif action == "mute":
                if self.player.volume() > 0:
                    self.player.mute()
                else:
                    self.player.unmute()
            elif action == "vol_up":
                new_volume = self.player.volume() + VOL_INCREMENT

                if new_volume > MAX_VOLUME:
                    self.player.set_volume(MAX_VOLUME)
                else:
                    self.player.set_volume(new_volume)
            elif action == "vol_down":
                new_volume = self.player.volume() - VOL_INCREMENT

                if new_volume < 0:
                    self.player.set_volume(0)
                else:
                    self.player.set_volume(new_volume)
            elif action == "skip_backward":
                new_position = self.player.position() - SKIP_INCREMENT

                if new_position < 0:
                    self.player.seek(0)
                else:
                    self.player.seek(new_position)
            elif action == "skip_forward":
                duration = self.player.duration()
                new_position = self.player.position() + SKIP_INCREMENT

                if new_position > duration:
                    # self.player.seek(0)
                    print("Cannot go past end of video")
                else:
                    self.player.seek(new_position)
        else:
            if action == "refresh":
                self.next()

    def next(self):
        self.currently_playing_ref.set(
            {
                "playingRef": None,
                "thumbnailLink": None,
                "fileName": None,
                "isPaused": False,
                "isLoading": True,
            }
        )

        if self.player:
            self.player.stop()
        else:
            self.start_player()

    def refresh(self, player, exit_code):
        self.start_player()

    def on_play(self, player):
        player_log.info("Play")

    def on_pause(self, player):
        player_log.info("Pause")

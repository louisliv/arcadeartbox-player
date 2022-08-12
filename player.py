import threading
import logging
from random import choice
import time
from typing import Optional

from google.cloud.storage import Bucket
from google.cloud.firestore import Client
import vlc

logging.basicConfig(level=logging.INFO)
player_log = logging.getLogger("Player 1")

SERVER_URL = f"https://firebasestorage.googleapis.com/v0/b/arcadeartbox.appspot.com/o"

VOL_INCREMENT = 10
MAX_VOLUME = 100
SKIP_INCREMENT = 0.1


class Player:
    end_volume = 50
    videos: dict = {}
    player: Optional[vlc.MediaPlayer] = None

    def __init__(
        self, firestore: Client, currently_playing_ref, storage_bucket: Bucket
    ):
        self.firestore = firestore
        self.storage_bucket = storage_bucket
        self.currently_playing_ref = currently_playing_ref
        self.instance = vlc.Instance()

        self.video_callback_done = threading.Event()

        col_query = self.firestore.collection("videos")

        # Watch the collection query
        col_query.on_snapshot(self.on_snapshot)

        global vidOver

        vidOver = False

        time.sleep(0.2)
        threading.Thread(target=self.check_for_end_video, args=(), daemon=True).start()

    def on_snapshot(self, col_snapshot: list, changes, read_time):
        self.videos = {snapshot.id: snapshot.to_dict() for snapshot in col_snapshot}

        if not self.player or not self.player.is_playing():
            self.start_player()

        self.video_callback_done.set()

    def start_player(self):
        if self.videos:
            self.create_player()

    def create_player(self):
        player_log.info("Starting player...")
        random_video_id = choice(list(self.videos.keys()))
        random_video = self.videos[random_video_id]

        file_path = random_video["file_path"]
        file_blob = self.storage_bucket.get_blob(file_path)

        file_metadata: dict = file_blob.metadata
        file_token = file_metadata.get("firebaseStorageDownloadTokens")
        url = f"{SERVER_URL}/{file_path}?alt=media&token={file_token}"
        player_log.info("got url...")

        if not self.player:
            player_log.info("Creating player...")

            self.player: vlc.MediaPlayer = self.instance.media_player_new(url)
            self.player.set_fullscreen(True)

            player_log.info("Creating event manager...")
            events: vlc.EventManager = self.player.event_manager()
            events.event_attach(vlc.EventType.MediaPlayerEndReached, self.on_finished)

        player_log.info("Creating media...")
        media: vlc.Media = self.instance.media_new(url)

        player_log.info("Setting media...")
        self.player.set_media(media)
        media.release()

        player_log.info("Playing media...")
        self.player.audio_set_volume(self.end_volume)
        self.player.play()
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
        if self.player:
            if action == "refresh":
                self.next()
            elif action == "pause":
                self.player.pause()
                self.currently_playing_ref.set({"isPaused": True}, merge=True)
            elif action == "play":
                self.player.play()
                self.currently_playing_ref.set({"isPaused": False}, merge=True)
            elif action == "mute":
                self.player.audio_toggle_mute()
            elif action == "vol_up":
                new_volume = self.player.audio_get_volume() + VOL_INCREMENT

                if new_volume > MAX_VOLUME:
                    self.player.audio_set_volume(MAX_VOLUME)
                else:
                    self.player.audio_set_volume(new_volume)
            elif action == "vol_down":
                new_volume = self.player.audio_get_volume() - VOL_INCREMENT

                if new_volume < 0:
                    self.player.audio_set_volume(0)
                else:
                    self.player.audio_set_volume(new_volume)
            elif action == "skip_backward":
                if not self.player.is_seekable():
                    return

                new_position = self.player.get_position() - SKIP_INCREMENT

                if new_position < 0:
                    self.player.set_position(0)
                else:
                    self.player.set_position(new_position)
            elif action == "skip_forward":
                if not self.player.is_seekable():
                    return

                new_position = self.player.get_position() + SKIP_INCREMENT

                if new_position > 1:
                    print("Cannot go past end of video")
                else:
                    self.player.set_position(new_position)
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
            self.end_volume = self.player.audio_get_volume()

        self.start_player()

    def check_for_end_video(self):
        global vidOver
        vidOver = False
        while True:
            if vidOver is True:
                vidOver = False
                self.next()
            time.sleep(0.2)

    def on_finished(self, event):
        if event.type == vlc.EventType.MediaPlayerEndReached:
            global vidOver
            vidOver = True
            player_log.info("Video finished")

# bridge/management/commands/eval_bridge_moderation.py
#
# Phase A-10 evaluation: confirm LiveKit moderation primitives work against
# local livekit-server. Requires a running livekit-server on localhost:7880
# (docker compose -f docker/livekit-local.yml up) and a live BridgeSession
# with at least one connected participant.
#
# Usage:
#   python manage.py eval_bridge_moderation --room bridge-test-001
#   python manage.py eval_bridge_moderation --room bridge-test-001 --identity <user-uuid> --mute
#   python manage.py eval_bridge_moderation --room bridge-test-001 --identity <user-uuid> --remove
#   python manage.py eval_bridge_moderation --room bridge-test-001 --lock
#   python manage.py eval_bridge_moderation --room bridge-test-001 --list-participants

import asyncio

from django.conf import settings
from django.core.management.base import BaseCommand

from livekit import api as lk_api


class Command(BaseCommand):
    help = "Evaluate LiveKit moderation primitives (Phase A-10)"

    def add_arguments(self, parser):
        parser.add_argument("--room", required=True, help="Room name to target")
        parser.add_argument("--identity", default=None, help="Participant identity for mute/remove")
        parser.add_argument("--list-participants", action="store_true")
        parser.add_argument("--mute", action="store_true", help="Mute first audio track of --identity")
        parser.add_argument("--remove", action="store_true", help="Remove --identity from room")
        parser.add_argument("--lock", action="store_true", help="Set max_participants=1 to lock room")

    def handle(self, *args, **options):
        asyncio.run(self._run(options))

    async def _run(self, options):
        room_name = options["room"]
        identity = options.get("identity")

        livekit_url = settings.LIVEKIT_URL.replace("ws://", "http://").replace("wss://", "https://")

        room_svc = lk_api.RoomServiceClient(
            livekit_url,
            settings.LIVEKIT_API_KEY,
            settings.LIVEKIT_API_SECRET,
        )

        if options["list_participants"]:
            await self._list_participants(room_svc, room_name)

        if options["mute"]:
            if not identity:
                self.stderr.write("--identity required for --mute")
                return
            await self._mute_participant(room_svc, room_name, identity)

        if options["remove"]:
            if not identity:
                self.stderr.write("--identity required for --remove")
                return
            await self._remove_participant(room_svc, room_name, identity)

        if options["lock"]:
            await self._lock_room(room_svc, room_name)

        if not any([options["list_participants"], options["mute"], options["remove"], options["lock"]]):
            self.stdout.write("No action specified. Use --list-participants, --mute, --remove, or --lock.")

    async def _list_participants(self, svc, room_name):
        self.stdout.write(f"Listing participants in room '{room_name}'...")
        participants = await svc.list_participants(room=room_name)
        if not participants:
            self.stdout.write("  (no participants)")
            return
        for p in participants:
            self.stdout.write(f"  identity={p.identity}  name={p.name}  tracks={len(p.tracks)}")

    async def _mute_participant(self, svc, room_name, identity):
        self.stdout.write(f"Fetching tracks for '{identity}' in '{room_name}'...")
        participants = await svc.list_participants(room=room_name)
        target = next((p for p in participants if p.identity == identity), None)
        if not target:
            self.stderr.write(f"Participant '{identity}' not found in room '{room_name}'")
            return

        audio_tracks = [t for t in target.tracks if t.type == 0]  # 0 = AUDIO
        if not audio_tracks:
            self.stderr.write(f"No audio track found for '{identity}'")
            return

        track_sid = audio_tracks[0].sid
        self.stdout.write(f"Muting track {track_sid}...")
        await svc.mute_published_track(
            room=room_name,
            identity=identity,
            track_sid=track_sid,
            muted=True,
        )
        self.stdout.write(self.style.SUCCESS(f"✓ Muted audio track {track_sid} for '{identity}'"))

    async def _remove_participant(self, svc, room_name, identity):
        self.stdout.write(f"Removing '{identity}' from '{room_name}'...")
        await svc.remove_participant(room=room_name, identity=identity)
        self.stdout.write(self.style.SUCCESS(f"✓ Removed '{identity}' from room '{room_name}'"))

    async def _lock_room(self, svc, room_name):
        self.stdout.write(f"Locking room '{room_name}' (max_participants=1)...")
        await svc.update_room_metadata(room=room_name, metadata="locked")
        self.stdout.write(self.style.SUCCESS(f"✓ Room '{room_name}' metadata set to 'locked'"))
        self.stdout.write("  Note: to restrict joins, use empty_timeout or max_participants on room creation.")
        self.stdout.write("  Phase B moderation: implement via RoomService.UpdateRoom (update_room not exposed")
        self.stdout.write("  in SDK v1 for max_participants — use HTTP TWIRP API directly if needed).")

"""Photo time (rituals/photo_time.py): the hub's side of the robot camera's face-signs moment."""

import asyncio

from kaiku_contracts.registry import EXAMPLES, payload_model
from kaiku_hub.rituals.photo_time import (
    DONE_LINE,
    NO_CAMERA_LINE,
    NO_FACE_LINE,
    START_LINE,
    PhotoTime,
    observation,
)


def validate_payload(type_, payload):
    payload_model(type_).model_validate(payload)


class Robot:
    def __init__(self):
        self.said, self.cmds, self.obs = [], [], []

    async def say(self, text):
        self.said.append(text)

    async def sensors(self, **cmd):
        validate_payload("cmd.sensors", cmd)
        self.cmds.append(cmd)

    async def emit(self, type_, payload, quality=None):
        validate_payload(type_, payload)
        self.obs.append((type_, payload, quality))


def test_the_observation_is_numbers_only_and_never_a_zero_for_an_unmeasured_sign():
    raw = dict(EXAMPLES["raw.sensors.face_signs"])
    obs = observation(raw)
    validate_payload("obs.face_signs", obs)
    assert (obs["task"], obs["device"], obs["method"]) == ("photo_time", "robot", "haar_cascades")
    assert obs["smiles"] == 2 and "blinks_per_min" not in obs
    none = observation({"duration_s": 8.0, "samples": 60, "coverage": 0.0})
    validate_payload("obs.face_signs", none)
    assert set(none) == {"task", "device", "method", "duration_s", "samples", "coverage"}


async def test_photo_time_says_it_asks_the_board_and_records_what_came_back():
    robot, pt = Robot(), PhotoTime(0.2)
    run = asyncio.create_task(pt.run(robot))
    await asyncio.sleep(0.05)
    assert robot.said == [START_LINE] and robot.cmds[0]["face_signs_s"] == 0.2 and pt.running
    assert (await pt.run(robot))["ok"] is False  # one window at a time
    pt.on_raw(dict(EXAMPLES["raw.sensors.face_signs"]))
    out = await run
    assert out["ok"] and out["counted"] and "smile" not in str(out).lower()  # the model never hears how she looked
    assert robot.said[-1] == DONE_LINE and robot.obs[0][0] == "obs.face_signs" and not pt.running


async def test_no_face_is_fine_and_a_silent_camera_is_said_plainly(monkeypatch):
    robot, pt = Robot(), PhotoTime(0.1)
    run = asyncio.create_task(pt.run(robot))
    await asyncio.sleep(0.02)
    pt.on_raw({"duration_s": 0.1, "samples": 3, "coverage": 0.0})
    out = await run
    assert out == {**out, "ok": True, "counted": False} and robot.said[-1] == NO_FACE_LINE  # nobody is asked to show a face
    monkeypatch.setattr("kaiku_hub.rituals.photo_time.WAIT_EXTRA_S", 0.05)
    robot = Robot()
    out = await PhotoTime(0.05).run(robot)
    assert out["ok"] is False and robot.said[-1] == NO_CAMERA_LINE and robot.obs == []

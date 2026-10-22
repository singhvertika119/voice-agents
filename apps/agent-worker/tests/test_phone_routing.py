from agent_worker.db import parse_room

AGENT = "0f8b1c3e-5a62-4c1d-9b7e-2d4f6a8c0e11"


def test_phone_room_names_route_to_the_agent_in_the_prefix():
    # LiveKit names an individual-rule room: <room_prefix><caller number>_<random>
    assert parse_room(f"live-{AGENT}-+14155550100_Xk3pQ9") == ("live", AGENT)
    assert parse_room(f"live-{AGENT}-_+919876543210_Xk3pQ9") == ("live", AGENT)
    assert parse_room(f"live-{AGENT}-") == ("live", AGENT)


def test_other_rooms_do_not_route():
    assert parse_room("call-+14155550100_Xk3pQ9") is None
    assert parse_room("live-not-a-uuid-abc") is None

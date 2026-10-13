from app.gestures.engine import GestureEngine, GestureName, HandLandmarks, Landmark


def make_hand(*, wrist_x: float = 0.5, index_y: float = 0.8, index_pip_y: float = 0.55, thumb_y: float = 0.55, middle: bool = False, ring: bool = False, pinky: bool = False) -> HandLandmarks:
    points = [Landmark(0.5, 0.5) for _ in range(21)]
    points[0] = Landmark(wrist_x, 0.7)
    points[3] = Landmark(0.4, 0.55)
    points[4] = Landmark(0.4, thumb_y)
    points[6], points[8] = Landmark(0.5, index_pip_y), Landmark(0.5, index_y)
    points[10], points[12] = Landmark(0.55, 0.55), Landmark(0.55, 0.25 if middle else 0.8)
    points[14], points[16] = Landmark(0.6, 0.55), Landmark(0.6, 0.25 if ring else 0.8)
    points[18], points[20] = Landmark(0.65, 0.55), Landmark(0.65, 0.25 if pinky else 0.8)
    return HandLandmarks(tuple(points))


def test_open_palm_and_thumbs_are_recognized() -> None:
    open_palm = make_hand(index_y=0.25, thumb_y=0.25, middle=True, ring=True, pinky=True)
    sideways_open_palm_points = list(make_hand(index_y=0.25, thumb_y=0.55, middle=True, ring=True, pinky=True).points)
    sideways_open_palm_points[4] = Landmark(0.25, 0.55)
    sideways_open_palm = HandLandmarks(tuple(sideways_open_palm_points))
    thumbs_up = make_hand(thumb_y=0.25)
    thumbs_down = make_hand(thumb_y=0.8)
    fist_points = list(make_hand().points)
    fist_points[4] = Landmark(0.51, 0.51)
    fist = HandLandmarks(tuple(fist_points))

    def recognize(hand):
        engine = GestureEngine()
        results = [engine.process(hand, 1 + index / 30) for index in range(6)]
        return next(result for result in results if result is not None)

    assert recognize(open_palm).gesture == GestureName.OPEN_PALM
    assert recognize(sideways_open_palm).gesture == GestureName.OPEN_PALM
    assert recognize(thumbs_up).gesture == GestureName.THUMBS_UP
    assert recognize(thumbs_down).gesture == GestureName.THUMBS_DOWN
    assert recognize(fist).gesture == GestureName.FIST


def test_swipe_right_matches_rightward_motion_in_mirrored_preview() -> None:
    engine = GestureEngine()

    assert engine.process(make_hand(wrist_x=0.5), 1.0) is None
    detection = engine.process(make_hand(wrist_x=0.2), 1.2)

    assert detection is not None
    assert detection.gesture == GestureName.SWIPE_RIGHT


def test_swipe_left_is_recognized() -> None:
    engine = GestureEngine()

    assert engine.process(make_hand(wrist_x=0.5), 1.0) is None
    detection = engine.process(make_hand(wrist_x=0.8), 1.2)

    assert detection is not None
    assert detection.gesture == GestureName.SWIPE_LEFT


def test_index_motion_controls_volume_direction() -> None:
    engine = GestureEngine()

    assert engine.process(make_hand(index_y=0.7), 1.0) is None
    detection = engine.process(make_hand(index_y=0.4), 1.2)

    assert detection is not None
    assert detection.gesture == GestureName.VOLUME_UP


def test_index_motion_controls_volume_down_direction() -> None:
    engine = GestureEngine()

    assert engine.process(make_hand(index_y=0.25), 1.0) is None
    detection = engine.process(make_hand(index_y=0.45, index_pip_y=0.65), 1.2)

    assert detection is not None
    assert detection.gesture == GestureName.VOLUME_DOWN


def test_two_raised_fingers_are_a_single_scroll_gesture_until_released() -> None:
    engine = GestureEngine(cooldown_seconds=0, static_frames=3)
    hand = make_hand(index_y=0.25, middle=True)

    detections = [engine.process(hand, 1 + index / 30) for index in range(12)]

    assert [item.gesture for item in detections if item is not None] == [GestureName.TWO_FINGERS]


def test_open_palm_shape_during_swipe_does_not_emit_pause_first() -> None:
    engine = GestureEngine()
    open_hand_start = make_hand(wrist_x=0.5, index_y=0.25, thumb_y=0.25, middle=True, ring=True, pinky=True)
    open_hand_end = make_hand(wrist_x=0.2, index_y=0.25, thumb_y=0.25, middle=True, ring=True, pinky=True)

    assert engine.process(open_hand_start, 1.0) is None
    detection = engine.process(open_hand_end, 1.1)

    assert detection is not None
    assert detection.gesture == GestureName.SWIPE_RIGHT


def test_two_finger_vertical_motion_carries_scroll_direction() -> None:
    engine = GestureEngine()
    assert engine.process(make_hand(index_y=0.7, middle=True), 1.0) is None
    detection = engine.process(make_hand(index_y=0.4, middle=True), 1.1)

    assert detection is not None
    assert detection.gesture == GestureName.SCROLL
    assert detection.direction == "up"


def test_reset_clears_cooldown_and_motion_history() -> None:
    engine = GestureEngine(static_frames=1)
    hand = make_hand(index_y=0.25, middle=True)

    assert engine.process(hand, 1.0) is not None
    assert engine.process(hand, 1.1) is None
    engine.reset()

    assert engine.process(hand, 1.1) is not None


def test_thumb_direction_changes_trigger_without_needing_a_full_neutral_pose() -> None:
    engine = GestureEngine()
    thumbs_up = make_hand(thumb_y=0.25)
    thumbs_down = make_hand(thumb_y=0.8)

    first = next((result for i in range(6) if (result := engine.process(thumbs_up, 1 + i / 30))), None)
    second = next((result for i in range(6) if (result := engine.process(thumbs_down, 1.5 + i / 30))), None)

    assert first is not None and first.gesture == GestureName.THUMBS_UP
    assert second is not None and second.gesture == GestureName.THUMBS_DOWN


def test_short_swipe_is_detected_using_the_faster_default_threshold() -> None:
    engine = GestureEngine()

    assert engine.process(make_hand(wrist_x=0.5), 1.0) is None
    detection = engine.process(make_hand(wrist_x=0.39), 1.08)

    assert detection is not None
    assert detection.gesture == GestureName.SWIPE_RIGHT

from __future__ import annotations

from automation.flow_state_detector import FlowStateDetector


class _FakeLocator:
    def __init__(self, count: int) -> None:
        self._count = count
        self.first = self

    def count(self) -> int:
        return self._count

    def inner_text(self, timeout: int = 300) -> str:
        return ""


class _FakeContext:
    def __init__(
        self,
        *,
        text: str = "",
        buttons: list[str] | None = None,
        counts: dict[str, int] | None = None,
    ) -> None:
        self.text_snapshot = text
        self._buttons = list(buttons or [])
        self._counts = dict(counts or {})

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(self._counts.get(selector, 0))

    def evaluate(self, _script: str):
        return list(self._buttons)


def test_detector_classifies_selfie_input_plus_continue() -> None:
    detector = FlowStateDetector()
    context = _FakeContext(
        text="Para continuar toma una foto selfie",
        buttons=["Continuar"],
        counts={
            "input[type='file'], input[accept*='image'], #user_avatar": 1,
            "input": 1,
        },
    )

    snapshot = detector.snapshot("paripe.io", "proc-1", context, source="selfie_input")

    assert snapshot.state == FlowStateDetector.PHOTO_READY_TO_CONTINUE


def test_detector_classifies_real_block_with_final_button() -> None:
    detector = FlowStateDetector()
    context = _FakeContext(
        text="Pago RD$ 300 Estacion VNY2 Horario 05:00 am - 08:00 am Duracion 3 horas",
        buttons=["He llegado"],
        counts={"input": 0},
    )

    snapshot = detector.snapshot("compinche.io", "proc-2", context, source="final_button")

    assert snapshot.state == FlowStateDetector.FINAL_BUTTON_VISIBLE


def test_detector_does_not_accept_dashboard_he_llegado_as_final_button_visible() -> None:
    detector = FlowStateDetector()
    context = _FakeContext(
        text="Dashboard principal con accesos rapidos",
        buttons=["He llegado"],
        counts={"input": 0},
    )

    snapshot = detector.snapshot("ready4drive.com", "proc-3", context, source="dashboard")

    assert snapshot.state != FlowStateDetector.FINAL_BUTTON_VISIBLE


def test_detector_classifies_processing_state() -> None:
    detector = FlowStateDetector()
    context = _FakeContext(text="Estamos validando tu selfie. Espere por favor.", counts={"input": 0})

    snapshot = detector.snapshot("paripe.io", "proc-4", context, source="processing")

    assert snapshot.state == FlowStateDetector.SELFIE_PROCESSING


def test_detector_classifies_error_state() -> None:
    detector = FlowStateDetector()
    context = _FakeContext(text="Error: no se pudo validar la foto", counts={"input": 0})

    snapshot = detector.snapshot("paripe.io", "proc-5", context, source="error")

    assert snapshot.state == FlowStateDetector.ERROR


def test_detector_classifies_final_result() -> None:
    detector = FlowStateDetector()
    context = _FakeContext(text="Proceso completado correctamente. Success.", counts={"input": 0})

    snapshot = detector.snapshot("compinche.io", "proc-6", context, source="result")

    assert snapshot.state == FlowStateDetector.FINAL_RESULT


def test_detector_handles_fake_context_without_crashing() -> None:
    detector = FlowStateDetector()

    snapshot = detector.snapshot("ready4drive.com", "proc-7", object(), source="fake_context")

    assert snapshot.state == FlowStateDetector.UNKNOWN
    assert snapshot.text_preview == ""

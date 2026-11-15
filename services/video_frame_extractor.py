"""Saca de un video las fotos que de verdad sirven para el pool.

El orden de prioridad importa y no es obvio: **primero la cara, despues la
calidad**. Una foto sin cara no sirve NUNCA -el proceso la usa como selfie-,
mientras que una foto un poco blanda pero con la cara clara se usa
perfectamente. Por eso la cara es la condicion para entrar, y la nitidez y la
luz solo deciden cuales de las que tienen cara son las mejores.

Antes era al reves: se filtraba por nitidez y brillo, asi que un fotograma
del techo, nitido y bien iluminado, pasaba; y uno algo movido con la cara
perfecta se tiraba.

Dos reglas que no se pueden romper, porque el video es la prueba de trabajo
semanal del agente:

* Nunca devolver cero fotos por ser exigentes. Si ninguna tiene cara, se
  devuelven las mejores por calidad marcadas con `has_face=False`, y que
  decida quien revise. Dejar al agente sin lote por un filtro nuestro seria
  cobrarle a el nuestra exigencia.
* Si los clasificadores de cara no estan disponibles en esta instalacion, se
  trabaja como antes en vez de fallar.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExtractedFrame:
    path: Path
    frame_index: int
    timestamp_seconds: float
    blur_score: float
    brightness_score: float
    # Ancho de la cara mas grande dividido por el ancho del fotograma. 0 si no
    # se vio ninguna.
    face_score: float = 0.0
    has_face: bool = False


@dataclass(frozen=True)
class _Medicion:
    """Lo que se sabe de un fotograma ANTES de decidir si se guarda."""

    frame_index: int
    timestamp_seconds: float
    blur_score: float
    brightness_score: float
    face_score: float


class VideoFrameExtractor:
    # Una cara mas pequena que esto es alguien de fondo, no el agente.
    MIN_FACE_RATIO = 0.07
    # Para buscar caras no hace falta la resolucion entera: a 480 px de ancho
    # se detecta igual y cuesta una fraccion.
    ANCHO_DE_ANALISIS = 480

    _CASCADAS = ("haarcascade_frontalface_alt2.xml", "haarcascade_profileface.xml")

    def __init__(self) -> None:
        self._detectores = None

    def extract(
        self,
        video_path: str | Path,
        output_dir: str | Path,
        *,
        interval_seconds: float,
        max_frames: int,
        jpeg_quality: int,
        min_blur_score: float = 30.0,
        min_brightness: float = 35.0,
        max_brightness: float = 230.0,
        min_face_ratio: float | None = None,
    ) -> list[ExtractedFrame]:
        try:
            import cv2
        except Exception as exc:
            raise RuntimeError(
                "OpenCV no esta instalado. Instala opencv-python-headless para procesar videos."
            ) from exc

        source = Path(video_path)
        if not source.is_file():
            raise FileNotFoundError(f"Video no encontrado: {source}")
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        umbral_cara = self.MIN_FACE_RATIO if min_face_ratio is None else float(min_face_ratio)

        capture = cv2.VideoCapture(str(source))
        if not capture.isOpened():
            raise ValueError(f"No se pudo abrir el video: {source.name}")

        try:
            mediciones = self._medir(
                cv2,
                capture,
                interval_seconds=interval_seconds,
                max_frames=max_frames,
            )
            elegidas = self._elegir(
                mediciones,
                max_frames=max_frames,
                umbral_cara=umbral_cara,
                min_blur_score=min_blur_score,
                min_brightness=min_brightness,
                max_brightness=max_brightness,
            )
            return self._guardar(
                cv2,
                capture,
                elegidas,
                destination=destination,
                jpeg_quality=jpeg_quality,
                umbral_cara=umbral_cara,
            )
        finally:
            capture.release()

    # -- paso 1: mirar sin escribir -------------------------------------

    def _medir(self, cv2, capture, *, interval_seconds: float, max_frames: int) -> list[_Medicion]:
        """Recorre el video midiendo. NO escribe ningun JPG todavia.

        Antes se escribia cada fotograma al disco y se borraba si no pasaba el
        filtro. Con la cara como condicion eso serian decenas de escrituras y
        borrados por video para nada.
        """

        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        if fps <= 0:
            fps = 30.0
        intervalo = float(interval_seconds)
        paso = 1 if intervalo <= 0 else max(int(round(fps * intervalo)), 1)
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        # Cuantos fotogramas se MIRAN como mucho. Sin tope, un video largo con
        # un intervalo pequeno tardaria una eternidad.
        tope_de_muestras = max(int(max_frames), 1) * 8

        mediciones: list[_Medicion] = []
        vistos: set[str] = set()
        filtrar_repetidos = intervalo > 0
        indice = 0
        while total <= 0 or indice < total:
            if len(mediciones) >= tope_de_muestras:
                break
            capture.set(cv2.CAP_PROP_POS_FRAMES, indice)
            ok, frame = capture.read()
            if not ok:
                break
            if filtrar_repetidos:
                huella = self._simple_frame_hash(cv2, frame)
                if huella in vistos:
                    indice += paso
                    continue
                vistos.add(huella)
            gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            mediciones.append(
                _Medicion(
                    frame_index=indice,
                    timestamp_seconds=round(float(indice / fps), 2),
                    blur_score=round(float(cv2.Laplacian(gris, cv2.CV_64F).var()), 2),
                    brightness_score=round(float(gris.mean()), 2),
                    face_score=round(self._ratio_de_cara(cv2, gris), 4),
                )
            )
            indice += paso
        return mediciones

    # -- paso 2: decidir ------------------------------------------------

    def _elegir(
        self,
        mediciones: list[_Medicion],
        *,
        max_frames: int,
        umbral_cara: float,
        min_blur_score: float,
        min_brightness: float,
        max_brightness: float,
    ) -> list[_Medicion]:
        if not mediciones:
            raise ValueError("No se generaron fotos utiles desde el video.")

        # LA CONDICION: que haya cara. Si ninguna la tiene, no se devuelve
        # vacio: se sigue con todas y quien revise decidira.
        con_cara = [m for m in mediciones if m.face_score >= umbral_cara]
        candidatas = con_cara or mediciones

        # La calidad solo descarta lo irrecuperable, y solo si queda algo.
        utiles = [
            m
            for m in candidatas
            if m.blur_score >= min_blur_score
            and min_brightness <= m.brightness_score <= max_brightness
        ]
        if utiles:
            candidatas = utiles

        # Cara mas grande primero; a igualdad, la mas nitida.
        candidatas = sorted(
            candidatas, key=lambda m: (m.face_score, m.blur_score), reverse=True
        )[: max(int(max_frames), 1)]
        # Y se devuelven en orden del video, no de calidad: leerlas asi tiene
        # sentido para quien las revisa.
        return sorted(candidatas, key=lambda m: m.frame_index)

    # -- paso 3: escribir solo las elegidas ------------------------------

    def _guardar(
        self,
        cv2,
        capture,
        elegidas: list[_Medicion],
        *,
        destination: Path,
        jpeg_quality: int,
        umbral_cara: float,
    ) -> list[ExtractedFrame]:
        guardadas: list[ExtractedFrame] = []
        for medicion in elegidas:
            capture.set(cv2.CAP_PROP_POS_FRAMES, medicion.frame_index)
            ok, frame = capture.read()
            if not ok:
                continue
            path = destination / f"frame_{medicion.frame_index:08d}.jpg"
            cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
            guardadas.append(
                ExtractedFrame(
                    path=path,
                    frame_index=medicion.frame_index,
                    timestamp_seconds=medicion.timestamp_seconds,
                    blur_score=medicion.blur_score,
                    brightness_score=medicion.brightness_score,
                    face_score=medicion.face_score,
                    has_face=medicion.face_score >= umbral_cara,
                )
            )
        if not guardadas:
            raise ValueError("No se generaron fotos utiles desde el video.")
        return guardadas

    # -- la cara ---------------------------------------------------------

    def _ratio_de_cara(self, cv2, gris) -> float:
        """Ancho de la cara mas grande / ancho del fotograma. 0 si no hay.

        Se prueba de frente y, si no, de perfil en los dos sentidos: el
        clasificador de perfil solo mira hacia un lado, asi que la imagen
        espejada es la unica forma de ver el otro.
        """

        detectores = self._cargar_detectores(cv2)
        if not detectores:
            return 0.0
        alto, ancho = gris.shape[:2]
        if ancho <= 0:
            return 0.0
        escala = min(1.0, self.ANCHO_DE_ANALISIS / float(ancho))
        pequeno = (
            cv2.resize(gris, (int(ancho * escala), max(int(alto * escala), 1)))
            if escala < 1.0
            else gris
        )
        try:
            pequeno = cv2.equalizeHist(pequeno)
        except Exception:  # noqa: BLE001 - si no se puede igualar, se busca igual
            pass
        ancho_analisis = float(pequeno.shape[1]) or 1.0

        frontal, perfil = detectores
        intentos = [(frontal, pequeno)]
        if perfil is not None:
            intentos.append((perfil, pequeno))
            intentos.append((perfil, cv2.flip(pequeno, 1)))
        for clasificador, imagen in intentos:
            try:
                caras = clasificador.detectMultiScale(
                    imagen, scaleFactor=1.1, minNeighbors=5, minSize=(24, 24)
                )
            except Exception:  # noqa: BLE001 - un clasificador roto no tumba el video
                continue
            if len(caras):
                return max(float(w) for (_x, _y, w, _h) in caras) / ancho_analisis
        return 0.0

    def _cargar_detectores(self, cv2):
        """Los clasificadores, una vez. Lista vacia si no estan disponibles.

        OpenCV 5 dejo de incluirlos. `requirements.txt` fija <5.0 justo por
        esto, pero si alguna instalacion se sale de ahi se trabaja como antes
        -por calidad- en vez de fallar.
        """

        if self._detectores is not None:
            return self._detectores
        self._detectores = []
        try:
            base = cv2.data.haarcascades
            cargados = []
            for nombre in self._CASCADAS:
                clasificador = cv2.CascadeClassifier(base + nombre)
                cargados.append(None if clasificador.empty() else clasificador)
            if cargados and cargados[0] is not None:
                self._detectores = cargados
        except Exception:  # noqa: BLE001
            self._detectores = []
        return self._detectores

    @staticmethod
    def _simple_frame_hash(cv2, frame) -> str:
        small = cv2.resize(frame, (12, 12))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        average = float(gray.mean())
        bits = ["1" if value > average else "0" for row in gray for value in row]
        return "".join(bits)

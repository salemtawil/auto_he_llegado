"""Como se dice un plazo en esta app. Una sola forma, en todas las pantallas.

El agente y el administrador tienen que leer exactamente lo mismo del mismo
video. Dos formateadores parecidos acabarian discrepando -uno redondeando
hacia arriba y otro hacia abajo- y el agente veria "te queda 1 dia" el mismo
dia que el panel del admin lo da por vencido.
"""

from __future__ import annotations

from datetime import timedelta

#: A partir de aqui se avisa en ambar. Por debajo de esto el agente tiene que
#: ponerse con ello hoy o mañana, y el aviso deja de ser informativo.
DIAS_DE_AVISO = 3


def texto_de_plazo(plazo: timedelta) -> str:
    """Un plazo en palabras, sin redondear a cero.

    Los dias se cuentan por techo y no por suelo: un video subido hace un
    instante tiene 6 dias y 23 horas de vida, y decir "6 dias" el mismo dia
    que lo subio parece una cuenta rota. Por debajo de un dia se dan horas,
    que es donde la precision importa de verdad; y media hora que queda se
    dice "menos de 1 hora", nunca "0 horas", porque decirle a alguien que le
    quedan cero cuando todavia puede trabajar es el error mas caro de los dos.
    """

    segundos = max(int(plazo.total_seconds()), 0)
    if segundos >= 86400:
        dias = -(-segundos // 86400)
        return "1 dia" if dias == 1 else f"{dias} dias"
    horas = segundos // 3600
    if horas >= 1:
        return "1 hora" if horas == 1 else f"{horas} horas"
    return "menos de 1 hora"

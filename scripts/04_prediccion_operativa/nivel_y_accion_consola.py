"""Consola SAMI: amenaza -> moda de 5 días -> nivel -> acción (regla nueva, por torre y por día)."""
from collections import Counter

# 1) AMENAZA diaria: 0 baja, 1 media, 2 alta, 3 muy alta (cortes sobre el aporte de la lluvia, delta del FGAM).
#    Sin modelo espacio-temporal: la amenaza sale del pronóstico IDEAM contra umbrales (0 a 3) y el resto no cambia.
def amenaza(delta):
    return sum(delta >= corte for corte in (1.5, 2.5, 3.2))

# 2) AMENAZA CONFIRMADA = moda de los últimos 5 días (hasta ayer). Empate -> clase más alta.
#    Los días sin dato (-1) no cuentan; con menos de 3 días válidos no hay confirmación (None).
def moda(ultimos_5):
    validos = [a for a in ultimos_5 if a >= 0]
    if len(validos) < 3:
        return None
    c = Counter(validos)
    return max(c, key=lambda k: (c[k], k))

# 3) NIVEL (1 a 5; 0 = sin dato)
MATRIZ = [[1, 1, 2, 2],      # filas: amenaza confirmada (baja, media, alta, muy alta)
          [1, 2, 2, 3],      # columnas: prospección del mes D (baja, media, alta, muy alta)
          [2, 3, 3, 4],
          [3, 3, 4, 5]]
D_A_CLASE = {1: 0, 2: 0, 3: 1, 4: 2, 5: 3}       # D de 1 a 5 -> clase de la columna

def nivel(confirmada, D, max_180d, criticidad):
    if confirmada is None or D is None:
        return 0
    col = D_A_CLASE[D]
    n = MATRIZ[confirmada][col]
    if max_180d >= 2 and confirmada >= 1 and col >= 1 and n <= 2:   # historia alta: sube 1, hasta el nivel 3
        n += 1
    if n == 5 and criticidad not in ("A", "B"):                    # nivel 5 solo en líneas de criticidad A o B
        n = 4
    return n

# 4) ACCIÓN. dias4 / dias5 = días seguidos, hasta hoy, en nivel >= 4 / nivel 5 (ver racha).
def racha(niveles, umbral):
    n = 0
    for x in reversed(niveles):
        if x < umbral:
            break
        n += 1
    return n

def accion(niv, dias4, dias5, alerta_temprana=False):
    if niv == 0:
        return "Completar información"
    if niv == 5 and dias5 >= 7:
        return "Confirmar emergencia"
    if niv >= 4 and dias4 >= 7:
        return "Confirmar intervención inmediata"
    if alerta_temprana and niv < 4:
        return "Verificación prioritaria"
    return ["", "Sin acción", "Monitoreo", "Atención focalizada",
            "Verificación prioritaria", "Verificación prioritaria"][niv]


if __name__ == "__main__":
    amen_5d = [amenaza(d) for d in (2.7, 3.4, 3.3, 1.6, 3.5)]          # [2, 3, 3, 1, 3]
    conf = moda(amen_5d)                                               # 3 (muy alta)
    niv = nivel(conf, D=4, max_180d=3, criticidad="A")                 # 4
    print(amen_5d, conf, niv, accion(niv, dias4=racha([4] * 7, 4), dias5=0))
    print(nivel(3, 5, 3, "C"), nivel(0, 4, 3, "A"), nivel(None, 4, 0, "A"), moda([1, 2, 2, 1, -1]))

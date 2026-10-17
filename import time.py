
import time
import threading
import keyboard
import pydirectinput

# ===== CONFIGURAÇÕES =====
TEMPO_PRESSIONADO = 0.108
TEMPO_SOLTO = 0.145

executando = threading.Event()
encerrado = threading.Event()

pydirectinput.PAUSE = 0


def pescar():
    while not encerrado.is_set():
        if not executando.is_set():
            time.sleep(0.01)
            continue

        try:
            pydirectinput.keyDown("enter")
            inicio = time.monotonic()

            while (
                time.monotonic() - inicio < TEMPO_PRESSIONADO
                and executando.is_set()
                and not encerrado.is_set()
            ):
                time.sleep(0.005)

        finally:
            # Sempre libera a tecla ao terminar cada ciclo
            pydirectinput.keyUp("enter")

        if executando.is_set() and not encerrado.is_set():
            fim = time.monotonic() + TEMPO_SOLTO

            while (
                time.monotonic() < fim
                and executando.is_set()
                and not encerrado.is_set()
            ):
                time.sleep(0.005)


def alternar():
    if executando.is_set():
        executando.clear()
        pydirectinput.keyUp("enter")
        print("PAUSADO")
    else:
        executando.set()
        print("ATIVO")


print("F6 = iniciar/pausar | ESC = encerrar")

thread = threading.Thread(target=pescar, daemon=True)
thread.start()

keyboard.add_hotkey("F6", alternar)

try:
    keyboard.wait("esc")
finally:
    encerrado.set()
    executando.clear()
    pydirectinput.keyUp("enter")
    thread.join(timeout=2)
    keyboard.unhook_all()
    print("Encerrado")
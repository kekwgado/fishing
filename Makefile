# ==============================================================================
# Makefile — Automação de Pesca Inteligente (GTA RP / FiveM)
# ==============================================================================

PYTHON ?= python

.PHONY: all run run-circulo test install clean help

all: help

run:
	@echo "Iniciando Bot Completo (Barra Cinza + Disco Cadenciado + Guardar Peixe)..."
	$(PYTHON) pesca_auto_corrigido.py

run-circulo:
	@echo "Iniciando Bot Direto no Minigame Circular (Disco Cadenciado + Guardar Peixe)..."
	$(PYTHON) pesca_circulo.py

test:
	@echo "Executando suite de testes offline com as 3 imagens de referencia..."
	$(PYTHON) pesca_circulo.py --test

install:
	@echo "Instalando dependencias via pip..."
	$(PYTHON) -m pip install -r requirements.txt

clean:
	@echo "Limpando arquivos temporarios e caches..."
	@rm -rf __pycache__ *.pyc .pytest_cache
	@echo "Limpeza concluida."

help:
	@echo "====================================================================="
	@echo "            PESCA AUTOMATICA INTELIGENTE — COMANDOS MAKE             "
	@echo "====================================================================="
	@echo "  make run          : Inicia o bot completo (Barra + Disco + Guardar)"
	@echo "  make run-circulo  : Inicia direto no Minigame Circular"
	@echo "  make test         : Executa os 3 testes offline com as imagens"
	@echo "  make install      : Instala dependencias do requirements.txt"
	@echo "  make clean        : Remove caches e arquivos temporarios"
	@echo "====================================================================="

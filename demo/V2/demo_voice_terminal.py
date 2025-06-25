#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo_voice_terminal.py – голосовой интерфейс управления Piper через PiperTerminal.

Зависимости (добавлены в requirements.txt):
    openai           – вызов GPT-4o
    langchain        – tool-calling + управление историей
    speechrecognition + openai-whisper – ASR
    elevenlabs       – TTS
    sounddevice/soundfile – захват аудио (SpeechRecognition тоже умеет)

Перед запуском выставьте переменные окружения:
    OPENAI_API_KEY          – ключ OpenAI
    ELEVENLABS_API_KEY      – ключ ElevenLabs (https://elevenlabs.io)

Сценарий:
    1. Запустите скрипт – микрофон слушает в фоне.
    2. Произнесите команду обычным языком, напр.:
         «возьми из холодильника коробку один и положи на стол»
    3. Whisper -> текст -> LLM (с инструментами PiperTerminal) -> вызов -> короткий TTS-ответ.
"""
from __future__ import annotations

import os
import queue
import time

import openai
from langchain.tools import Tool
from langchain.agents import initialize_agent, AgentType
from langchain.chat_models import ChatOpenAI
from langchain.memory import ConversationBufferMemory

import speech_recognition as sr
from elevenlabs import generate, play, set_api_key

from demo.V2.demo_terminal import PiperTerminal, DELAY_BETWEEN_TRACKS

# ---------------------------------------------------- ASR/TTS helpers

WHISPER_MODEL = "base"  # локальная модель для SpeechRecognition

set_api_key(os.getenv("ELEVENLABS_API_KEY", ""))


def tts_say(text: str, voice: str = "Bella") -> None:
    """Синтезирует и воспроизводит короткую фразу."""
    try:
        audio = generate(text=text, voice=voice, model="eleven_multilingual_v2")
        play(audio)
    except Exception as e:  # noqa: BLE001
        print("[TTS ERROR]", e)


# ---------------------------------------------------- Voice terminal class


class PiperVoiceTerminal:
    """Голосовой интерфейс. Под капотом использует PiperTerminal."""

    def __init__(self) -> None:
        self.terminal = PiperTerminal()

        # ------------- LangChain agent
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        memory = ConversationBufferMemory(memory_key="chat_history",
                                           return_messages=True)
        self.agent = initialize_agent(
            tools=self._build_tools(),
            llm=llm,
            agent=AgentType.OPENAI_FUNCTIONS,
            verbose=False,
            memory=memory,
        )

        # ------------- Speech recognition
        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source)
        self._audio_queue: queue.Queue = queue.Queue()
        self._stop_listen = None  # type: ignore

    # --------------------- tools --------------------
    def _build_tools(self):
        return [
            Tool(
                name="status",
                description="Получить status выбранной руки. arg 'arm' = 'l'|'r'|'b'",
                func=lambda arm: self.terminal.cmd_status(arm),
            ),
            Tool(
                name="enable",
                description="Включить сервоприводы руки arm (l/r/b)",
                func=lambda arm: self.terminal.cmd_enable(arm),
            ),
            Tool(
                name="disable",
                description="Выключить сервоприводы руки arm (l/r/b)",
                func=lambda arm: self.terminal.cmd_disable(arm),
            ),
            Tool(
                name="play",
                description="Воспроизвести список треков последовательно. arg = список полных имён через пробел",
                func=lambda *tracks: self.terminal.cmd_play(*tracks),
            ),
            Tool(
                name="play_reverse",
                description="play_reverse parent child (полные имена)",
                func=lambda p, c: self.terminal.cmd_play_reverse(p, c),
            ),
            Tool(
                name="to_start",
                description="Переместить руку в начало трека full_name",
                func=lambda name: self.terminal.cmd_to_start(name),
            ),
            Tool(
                name="to_end",
                description="Переместить руку в конец трека full_name",
                func=lambda name: self.terminal.cmd_to_end(name),
            ),
        ]

    # --------------------- main loop ---------------
    def start(self):
        print("Voice terminal ready. Говорите команду… (Ctrl+C для выхода)")
        self._stop_listen = self.recognizer.listen_in_background(
            self.microphone, self._callback, phrase_time_limit=8
        )
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\nЗавершаю…")
        finally:
            if self._stop_listen:
                self._stop_listen(wait_for_stop=False)
            self.terminal.left_arm.DisconnectPort()
            self.terminal.right_arm.DisconnectPort()

    # --------------------- SR callback -------------
    def _callback(self, recognizer: sr.Recognizer, audio: sr.AudioData):  # noqa: D401
        try:
            text = recognizer.recognize_whisper(audio, model=WHISPER_MODEL, language="russian").lower()
            print("[ASR]", text)
            self._handle_command(text)
        except sr.UnknownValueError:
            print("[ASR] не разобрано…")
        except Exception as e:  # noqa: BLE001
            print("[ASR ERROR]", e)

    # --------------------- LLM handling ------------
    def _handle_command(self, user_text: str):
        # Документы контекста – список доступных треков
        tracks_list = "\n".join(sorted(self.terminal._all_tracks()))
        system_prompt = (
            "Ты управляешь роботом Piper. Вызывай инструменты строго когда нужно."\
            "Список треков доступных сейчас:\n" + tracks_list +
            "\nЕсли пользователь просит взять коробку/открыть дверцу и т.п. – подбери правильные имена треков."\
            f"Задержка между треками {DELAY_BETWEEN_TRACKS} c\n"
        )
        openai.api_key = os.getenv("OPENAI_API_KEY")
        # Помещаем system_prompt перед вызовом агента (LangChain memory уже учитывает историю)
        self.agent.agent.llm_kwargs = {"messages": [{"role": "system", "content": system_prompt}]}
        try:
            response = self.agent.run(user_text)
            if response:
                print("[LLM]", response)
                tts_say(response)
        except Exception as e:  # noqa: BLE001
            print("[LLM ERROR]", e)
            tts_say("Произошла ошибка")


# --------------------------------------------------------------------
if __name__ == "__main__":
    PiperVoiceTerminal().start() 
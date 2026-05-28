from pathlib import Path
import asyncio
import edge_tts as _edge_tts_mod
from core.utils import *

# Available voices can be listed using edge-tts --list-voices command
# Common English voices:
# en-US-JennyNeural - Female
# en-US-GuyNeural - Male
# en-GB-SoniaNeural - Female British
# Common Chinese voices:
# zh-CN-XiaoxiaoNeural - Female
# zh-CN-YunxiNeural - Male
# zh-CN-XiaoyiNeural - Female

async def _async_save(text, voice, path, rate):
    communicate = _edge_tts_mod.Communicate(text, voice, rate=rate)
    await communicate.save(path)

def edge_tts(text, save_path):
    # Load settings from config file
    edge_set = load_key("edge_tts")
    voice = edge_set.get("voice", "en-US-JennyNeural")
    # rate: edge-tts SSML rate, e.g. "-20%" slower, "+30%" faster. Default "+0%".
    rate = edge_set.get("rate", "+0%")

    # Create output directory if it doesn't exist
    speech_file_path = Path(save_path)
    speech_file_path.parent.mkdir(parents=True, exist_ok=True)

    # Use direct async API instead of subprocess to avoid PATH/exe lookup issues
    # (subprocess can hit WinError 2 in Streamlit threadpool context)
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're inside an event loop (rare here); run in new thread loop
            import threading
            err = [None]
            def _runner():
                try:
                    asyncio.run(_async_save(text, voice, str(speech_file_path), rate))
                except Exception as e:
                    err[0] = e
            t = threading.Thread(target=_runner)
            t.start()
            t.join()
            if err[0]:
                raise err[0]
        else:
            asyncio.run(_async_save(text, voice, str(speech_file_path), rate))
    except RuntimeError:
        # No current event loop
        asyncio.run(_async_save(text, voice, str(speech_file_path), rate))

    print(f"Audio saved to {speech_file_path}")

if __name__ == "__main__":
    edge_tts("Today is a good day!", "edge_tts.wav")

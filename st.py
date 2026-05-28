import streamlit as st
import os, sys, time
from core.st_utils.imports_and_utils import *
from core.st_utils.task_runner import TaskRunner
from core import *

# SET PATH
current_dir = os.path.dirname(os.path.abspath(__file__))
os.environ["PATH"] += os.pathsep + current_dir
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

st.set_page_config(page_title="VideoLingo", page_icon="docs/logo.svg")

SUB_VIDEO = "output/output_sub.mp4"
DUB_VIDEO = "output/output_dub.mp4"


# ─── Task control UI (auto-refreshes every 1s while task is active) ───


@st.fragment(run_every=1)
def _task_control_panel(runner_key: str):
    """Renders progress bar + pause/stop buttons. Auto-refreshes every 1s."""
    runner = TaskRunner.get(st.session_state, runner_key)

    if runner.state == "idle":
        return

    # Progress
    step_text = (
        f"({runner.current_step + 1}/{runner.total_steps}) {runner.current_label}"
        if runner.current_step >= 0
        else ""
    )

    if runner.is_active:
        if runner.state == "paused":
            st.warning(f"⏸️ {t('Paused')} {step_text}")
        else:
            st.info(f"⏳ {t('Running...')} {step_text}")
        st.progress(runner.progress)

        # Control buttons
        col1, col2 = st.columns(2)
        with col1:
            if runner.state == "paused":
                if st.button(
                    f"▶️ {t('Resume')}",
                    key=f"{runner_key}_resume",
                    use_container_width=True,
                ):
                    runner.resume()
                    st.rerun()
            else:
                if st.button(
                    f"⏸️ {t('Pause')}",
                    key=f"{runner_key}_pause",
                    use_container_width=True,
                ):
                    runner.pause()
                    st.rerun()
        with col2:
            if st.button(
                f"⏹️ {t('Stop')}",
                key=f"{runner_key}_stop",
                use_container_width=True,
                type="primary",
            ):
                runner.stop()
                st.rerun()

    elif runner.state == "completed":
        st.success(t("Task completed!"))
        st.progress(1.0)
        runner.reset()
        time.sleep(0.5)
        st.rerun(scope="app")

    elif runner.state == "stopped":
        st.warning(f"⏹️ {t('Task stopped')} {step_text}")
        if st.button(t("OK"), key=f"{runner_key}_ack_stop", use_container_width=True):
            runner.reset()
            st.rerun(scope="app")

    elif runner.state == "error":
        st.error(f"❌ {t('Task error')}: {runner.error_msg}")
        if st.button(t("OK"), key=f"{runner_key}_ack_error", use_container_width=True):
            runner.reset()
            st.rerun(scope="app")


# ─── Text processing ───


def _get_text_steps():
    """Return the subtitle processing steps as (label, callable) list."""
    steps = [
        (t("WhisperX word-level transcription"), _2_asr.transcribe),
        (
            t("Sentence segmentation using NLP and LLM"),
            lambda: (
                _3_1_split_nlp.split_by_spacy(),
                _3_2_split_meaning.split_sentences_by_meaning(),
            ),
        ),
        (
            t("Summarization and multi-step translation"),
            lambda: (_4_1_summarize.get_summary(), _4_2_translate.translate_all()),
        ),
        (
            t("Cutting and aligning long subtitles"),
            lambda: (
                _5_split_sub.split_for_sub_main(),
                _6_gen_sub.align_timestamp_main(),
            ),
        ),
        (
            t("Merging subtitles into the video"),
            _7_sub_into_vid.merge_subtitles_to_video,
        ),
    ]
    return steps


def text_processing_section():
    st.header(t("b. Translate and Generate Subtitles"))
    runner = TaskRunner.get(st.session_state, "_text_runner")

    with st.container(border=True):
        st.markdown(
            f"""
        <p style='font-size: 20px;'>
        {t("This stage includes the following steps:")}
        <p style='font-size: 20px;'>
            1. {t("WhisperX word-level transcription")}<br>
            2. {t("Sentence segmentation using NLP and LLM")}<br>
            3. {t("Summarization and multi-step translation")}<br>
            4. {t("Cutting and aligning long subtitles")}<br>
            5. {t("Generating timeline and subtitles")}<br>
            6. {t("Merging subtitles into the video")}
        """,
            unsafe_allow_html=True,
        )

        if not os.path.exists(SUB_VIDEO):
            if runner.is_active:
                _task_control_panel("_text_runner")
            elif runner.is_done:
                _task_control_panel("_text_runner")
            else:
                if st.button(
                    t("Start Processing Subtitles"), key="text_processing_button"
                ):
                    steps = _get_text_steps()
                    runner.start(steps)
                    st.rerun()
        else:
            if load_key("burn_subtitles"):
                st.video(SUB_VIDEO)
            download_subtitle_zip_button(text=t("Download All Srt Files"))

            if st.button(t("Archive to 'history'"), key="cleanup_in_text_processing"):
                cleanup()
                st.rerun()
            return True


# ─── Audio processing ───


def _get_audio_steps():
    """Return the audio/dubbing processing steps as (label, callable) list."""
    steps = [
        (
            t("Generate audio tasks and chunks"),
            lambda: (
                _8_1_audio_task.gen_audio_task_main(),
                _8_2_dub_chunks.gen_dub_chunks(),
            ),
        ),
        (t("Extract reference audio"), _9_refer_audio.extract_refer_audio_main),
        (t("Generate and merge audio files"), _10_gen_audio.gen_audio),
        (t("Merge full audio"), _11_merge_audio.merge_full_audio),
        (t("Merge final audio into video"), _12_dub_to_vid.merge_video_audio),
    ]
    return steps


def _dubbing_controls():
    """Render adjustable dub options. Saves to config.yaml on change."""
    import shutil

    EDGE_VOICE_PRESETS = {
        "Khmer Female (km-KH-SreymomNeural)": "km-KH-SreymomNeural",
        "Khmer Male (km-KH-PisethNeural)": "km-KH-PisethNeural",
        "Chinese Female (zh-CN-XiaoxiaoNeural)": "zh-CN-XiaoxiaoNeural",
        "Chinese Male (zh-CN-YunxiNeural)": "zh-CN-YunxiNeural",
        "English Female (en-US-JennyNeural)": "en-US-JennyNeural",
        "English Male (en-US-GuyNeural)": "en-US-GuyNeural",
    }

    with st.expander(f"⚙️ {t('Advanced Dubbing Options')}", expanded=False):
        st.caption(t("Changes save to config.yaml. Clear cache after change to take effect on already-generated audio."))

        # ─── Edge TTS voice ───
        cur_voice = load_key("edge_tts.voice")
        voice_labels = list(EDGE_VOICE_PRESETS.keys())
        voice_values = list(EDGE_VOICE_PRESETS.values())
        try:
            cur_idx = voice_values.index(cur_voice)
        except ValueError:
            cur_idx = 0
        sel_label = st.selectbox(
            f"🎤 {t('TTS Voice')}", voice_labels, index=cur_idx, key="dub_voice"
        )
        new_voice = EDGE_VOICE_PRESETS[sel_label]
        if new_voice != cur_voice:
            update_key("edge_tts.voice", new_voice)

        # ─── TTS base rate ───
        cur_rate_str = str(load_key("edge_tts.rate") if "rate" in (load_key("edge_tts") or {}) else "+0%")
        try:
            cur_rate_int = int(cur_rate_str.replace("%", "").replace("+", ""))
        except ValueError:
            cur_rate_int = 0
        new_rate_int = st.slider(
            f"🐢 {t('TTS Base Rate (%)')}",
            min_value=-50, max_value=30, value=cur_rate_int, step=5,
            help=t("Negative = slower, positive = faster"),
            key="dub_rate",
        )
        new_rate_str = f"{'+' if new_rate_int >= 0 else ''}{new_rate_int}%"
        if new_rate_str != cur_rate_str:
            update_key("edge_tts.rate", new_rate_str)

        # ─── Final video speed ───
        try:
            cur_fvs = float(load_key("final_video_speed"))
        except (KeyError, TypeError, ValueError):
            cur_fvs = 1.0
        new_fvs = st.slider(
            f"🎬 {t('Final Video Speed')}",
            min_value=0.70, max_value=1.30, value=float(cur_fvs), step=0.05,
            help=t("Multiplier applied to final dubbed video (video + audio together)"),
            key="dub_final_speed",
        )
        if abs(new_fvs - cur_fvs) > 1e-4:
            update_key("final_video_speed", round(float(new_fvs), 3))

        # ─── speed_factor.accept / max ───
        col1, col2 = st.columns(2)
        with col1:
            cur_accept = float(load_key("speed_factor.accept"))
            new_accept = st.slider(
                f"⚡ {t('Pipeline Accept Speed')}",
                min_value=1.00, max_value=1.50, value=cur_accept, step=0.05,
                help=t("Max comfortable speed-up applied by audio pipeline"),
                key="dub_speed_accept",
            )
            if abs(new_accept - cur_accept) > 1e-4:
                update_key("speed_factor.accept", round(float(new_accept), 3))
        with col2:
            cur_max = float(load_key("speed_factor.max"))
            new_max = st.slider(
                f"⚠️ {t('Pipeline Max Speed')}",
                min_value=1.05, max_value=1.60, value=cur_max, step=0.05,
                help=t("Hard cap on pipeline speed-up"),
                key="dub_speed_max",
            )
            if abs(new_max - cur_max) > 1e-4:
                update_key("speed_factor.max", round(float(new_max), 3))

        # ─── Reset dub cache button ───
        if st.button(
            f"🗑️ {t('Clear dub cache (segs + tmp)')}",
            key="dub_clear_cache",
            help=t("Forces TTS audio regeneration on next run"),
        ):
            shutil.rmtree("output/audio/segs", ignore_errors=True)
            shutil.rmtree("output/audio/tmp", ignore_errors=True)
            for f in ("output/dub.mp3", "output/dub.srt", "output/normalized_dub.wav"):
                try:
                    os.remove(f)
                except FileNotFoundError:
                    pass
            st.success(t("Dub cache cleared"))


def audio_processing_section():
    st.header(t("c. Dubbing"))
    runner = TaskRunner.get(st.session_state, "_audio_runner")

    with st.container(border=True):
        st.markdown(
            f"""
        <p style='font-size: 20px;'>
        {t("This stage includes the following steps:")}
        <p style='font-size: 20px;'>
            1. {t("Generate audio tasks and chunks")}<br>
            2. {t("Extract reference audio")}<br>
            3. {t("Generate and merge audio files")}<br>
            4. {t("Merge final audio into video")}
        """,
            unsafe_allow_html=True,
        )

        # Always-visible advanced options (hide only while a task is running)
        if not runner.is_active:
            _dubbing_controls()

        if not os.path.exists(DUB_VIDEO):
            if runner.is_active:
                _task_control_panel("_audio_runner")
            elif runner.is_done:
                _task_control_panel("_audio_runner")
            else:
                if st.button(
                    t("Start Audio Processing"), key="audio_processing_button"
                ):
                    steps = _get_audio_steps()
                    runner.start(steps)
                    st.rerun()
        else:
            st.success(
                t(
                    "Audio processing is complete! You can check the audio files in the `output` folder."
                )
            )
            if load_key("burn_subtitles"):
                st.video(DUB_VIDEO)

            # Re-run dubbing button (uses current control settings)
            if st.button(
                f"🔁 {t('Regenerate dub with current settings')}",
                key="regen_dub_btn",
                help=t("Clears dub cache + output_dub.mp4 then re-runs dub pipeline"),
            ):
                import shutil
                shutil.rmtree("output/audio/segs", ignore_errors=True)
                shutil.rmtree("output/audio/tmp", ignore_errors=True)
                for f in (DUB_VIDEO, "output/dub.mp3", "output/dub.srt", "output/normalized_dub.wav"):
                    try:
                        os.remove(f)
                    except FileNotFoundError:
                        pass
                runner.start(_get_audio_steps())
                st.rerun()

            if st.button(t("Delete dubbing files"), key="delete_dubbing_files"):
                delete_dubbing_files()
                st.rerun()
            if st.button(t("Archive to 'history'"), key="cleanup_in_audio_processing"):
                cleanup()
                st.rerun()


# ─── Main ───


def main():
    logo_col, _ = st.columns([1, 1])
    with logo_col:
        st.image("docs/logo.png", width="stretch")
    st.markdown(button_style, unsafe_allow_html=True)
    welcome_text = t(
        'Hello, welcome to VideoLingo. If you encounter any issues, feel free to get instant answers with our Free QA Agent <a href="https://share.fastgpt.in/chat/share?shareId=066w11n3r9aq6879r4z0v9rh" target="_blank">here</a>! You can also try out our SaaS website at <a href="https://videolingo.io" target="_blank">videolingo.io</a> for free!'
    )
    st.markdown(
        f"<p style='font-size: 20px; color: #808080;'>{welcome_text}</p>",
        unsafe_allow_html=True,
    )
    # add settings
    with st.sidebar:
        page_setting()
        st.markdown(give_star_button, unsafe_allow_html=True)
    download_video_section()
    text_processing_section()
    audio_processing_section()


if __name__ == "__main__":
    main()

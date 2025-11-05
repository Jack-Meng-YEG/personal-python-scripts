#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
azure_ssml_to_wav.py  (robust split + synth + concat + optional mp3)

Fixes:
- Tolerate XML prolog like <?xml ...?> before <speak>
- Tolerate BOM/leading comments/blank lines
- Safer <speak> body extraction
- Better diagnostics

Usage:
  export SPEECH_KEY="..."
  export SPEECH_REGION="canadacentral"
  python3 azure_ssml_to_wav.py lesson01.ssml
"""

import os, sys, re, argparse, pathlib, time, wave, contextlib

try:
    import azure.cognitiveservices.speech as speechsdk
except Exception:
    speechsdk = None

def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def write_text(path, text):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

def normalize_prolog(ssml_text):
    # strip BOM
    if ssml_text and ssml_text[0] == "\ufeff":
        ssml_text = ssml_text[1:]
    # remove XML prolog if present
    ssml_text = re.sub(r'^\s*<\?xml[^>]*\?>\s*', '', ssml_text, flags=re.S)
    # remove top comments
    ssml_text = re.sub(r'^\s*<!--.*?-->\s*', '', ssml_text, flags=re.S)
    return ssml_text

def count_voice_elements(ssml):
    return len(re.findall(r"<\s*voice\b", ssml, flags=re.I))

def extract_speak_body(ssml_text):
    """
    Returns (open_tag, body, close_tag). Robust to xml prolog/comments.
    """
    txt = normalize_prolog(ssml_text)
    # Find opening <speak ...>
    m_open = re.search(r'<\s*speak\b[^>]*>', txt, flags=re.I|re.S)
    m_close = re.search(r'</\s*speak\s*>', txt, flags=re.I|re.S)
    if not m_open or not m_close:
        raise ValueError("Cannot find <speak> ... </speak> root. "
                         "Please ensure the SSML has a single <speak> element.")
    start = m_open.start()
    end = m_close.end()
    open_tag = m_open.group(0)
    close_tag = m_close.group(0)
    inner = txt[m_open.end():m_close.start()]
    return open_tag, inner, close_tag

def split_ssml_by_voice(ssml_text, max_voices=48):
    """
    Split by <voice> blocks so each part has <= max_voices voice elements.
    """
    open_tag, body, close_tag = extract_speak_body(ssml_text)
    # capture <voice ...> ... </voice>
    voice_blocks = re.findall(r'(?s)(<\s*voice\b[^>]*>.*?<\s*/\s*voice\s*>)', body, flags=re.I)
    if not voice_blocks:
        # fallback: treat body as a single block (still enclosed in <speak> ... </speak>)
        voice_blocks = [body]
    parts = []
    current = []
    for vb in voice_blocks:
        current.append(vb)
        if len(current) >= max_voices:
            parts.append(open_tag + "\n" + "\n".join(current) + "\n" + close_tag)
            current = []
    if current:
        parts.append(open_tag + "\n" + "\n".join(current) + "\n" + close_tag)
    return parts

def synthesize_to_wav(ssml_text, wav_path, key, region, retries=2):
    if speechsdk is None:
        raise RuntimeError("azure-cognitiveservices-speech not installed. pip install azure-cognitiveservices-speech")
    speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm
    )
    audio_config = speechsdk.audio.AudioOutputConfig(filename=wav_path)
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
    attempt = 0
    while attempt <= retries:
        attempt += 1
        try:
            result = synthesizer.speak_ssml_async(ssml_text).get()
        except Exception as ex:
            print(f"⚠️  合成异常（第 {attempt} 次）：{ex}")
            time.sleep(1.5 * attempt)
            continue
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            print(f"✅  合成完成: {wav_path}")
            return True
        elif result.reason == speechsdk.ResultReason.Canceled:
            details = speechsdk.CancellationDetails(result)
            err = details.error_details or ""
            code = getattr(details, "error_code", "Unknown")
            print("❌  合成失败（Canceled）")
            print(f"   原因: {details.reason}")
            print(f"   代码: {code}")
            print(f"   详情: {err}")
            if "ConnectionFailure" in str(code) or "timeout" in err.lower():
                if attempt <= retries:
                    print(f"   ↻ 重试中（{attempt}/{retries}）...")
                    time.sleep(1.5 * attempt)
                    continue
            return False
    return False

def concat_wavs(wav_paths, out_wav):
    if not wav_paths:
        raise ValueError("No WAV parts to concatenate.")
    params = None
    data_frames = []
    for p in wav_paths:
        with contextlib.closing(wave.open(p, 'rb')) as w:
            cur = (w.getnchannels(), w.getsampwidth(), w.getframerate())
            if params is None:
                params = cur
            elif cur != params:
                raise ValueError(f"WAV format mismatch in {p}: {cur} vs {params}")
            data_frames.append(w.readframes(w.getnframes()))
    d = os.path.dirname(out_wav)
    if d:
        os.makedirs(d, exist_ok=True)
    with contextlib.closing(wave.open(out_wav, 'wb')) as out:
        out.setnchannels(params[0])
        out.setsampwidth(params[1])
        out.setframerate(params[2])
        for frames in data_frames:
            out.writeframes(frames)
    print(f"✅  合并完成: {out_wav}")

def wav_to_mp3(in_wav, out_mp3):
    try:
        from pydub import AudioSegment
    except Exception:
        print("⚠️  pydub 未安装，跳过 MP3 转换。pip install pydub")
        return False
    AudioSegment.converter = os.getenv("FFMPEG_PATH") or "ffmpeg"
    audio = AudioSegment.from_wav(in_wav)
    audio.export(out_mp3, format="mp3", bitrate="160k")
    print(f"🎵  已输出 MP3: {out_mp3}")
    return True

def main():
    ap = argparse.ArgumentParser(description="Azure SSML → WAV parts → concat → (optional) MP3 (robust split)")
    ap.add_argument("ssml", help="输入的大 SSML 文件路径")
    ap.add_argument("--out", default="out", help="输出目录（默认 out）")
    ap.add_argument("--max-voices", type=int, default=48, help="每个分片最多 <voice> 数（默认 48）")
    ap.add_argument("--no-split", action="store_true", help="不拆分（手工已拆）")
    ap.add_argument("--to-mp3", action="store_true", help="最终额外导出 MP3（需 ffmpeg+pydub）")
    args = ap.parse_args()

    key = os.getenv("SPEECH_KEY") or os.getenv("AZURE_SPEECH_KEY")
    region = os.getenv("SPEECH_REGION") or os.getenv("AZURE_SPEECH_REGION") or "canadacentral"
    if not key:
        print("❌ 缺少环境变量 SPEECH_KEY。请先执行： export SPEECH_KEY=你的密钥")
        sys.exit(2)

    in_path = pathlib.Path(args.ssml).resolve()
    if not in_path.exists():
        print(f"❌ 找不到输入文件: {in_path}")
        sys.exit(3)

    out_dir = pathlib.Path(args.out).resolve()
    parts_dir = out_dir / "parts"
    wavs_dir = out_dir / "wavs"
    os.makedirs(parts_dir, exist_ok=True)
    os.makedirs(wavs_dir, exist_ok=True)

    part_paths = []
    if not args.no_split:
        ssml_text = read_text(str(in_path))
        total_voices = count_voice_elements(ssml_text)
        print(f"🔎 输入 SSML 含 <voice> 元素: {total_voices} 个")
        try:
            parts = split_ssml_by_voice(ssml_text, max_voices=args.max_voices)
        except Exception as e:
            print("❌ 拆分失败：", e)
            print("   提示：文件顶部若有 '<?xml ...?>' 或注释，会自动处理；若仍失败，请检查 <speak> 根元素是否成对出现。")
            sys.exit(4)
        for i, p in enumerate(parts, start=1):
            part_path = parts_dir / f"{in_path.stem}.part{i:02d}.ssml"
            write_text(str(part_path), p)
            part_paths.append(str(part_path))
        print(f"✂️  已拆分为 {len(part_paths)} 个分片（每个 ≤ {args.max_voices} 个 <voice>）。")
    else:
        part_paths = sorted(str(p) for p in parts_dir.glob("*.part*.ssml"))
        if not part_paths:
            print("❌ --no-split 模式下未找到任何 *.part*.ssml 分片。")
            sys.exit(5)

    wav_parts = []
    for pp in part_paths:
        wav_out = wavs_dir / (pathlib.Path(pp).stem + ".wav")
        ok = synthesize_to_wav(read_text(pp), str(wav_out), key, region)
        if not ok:
            print("❌ 某个分片合成失败，终止。")
            sys.exit(6)
        wav_parts.append(str(wav_out))

    final_wav = out_dir / (in_path.stem + ".final.wav")
    concat_wavs(wav_parts, str(final_wav))

    if args.to_mp3:
        final_mp3 = out_dir / (in_path.stem + ".final.mp3")
        wav_to_mp3(str(final_wav), str(final_mp3))

    print("✅ 全流程完成。输出目录:", out_dir)

if __name__ == "__main__":
    main()

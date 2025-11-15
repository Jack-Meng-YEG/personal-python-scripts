#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Azure Speech STT 实用脚本（单文件 & 批量）
用法示例：
  单文件中文：
    azure_speech_to_text.py -i ~/speechcli/audio/file.wav -l zh-CN
  批量处理目录中所有音频（中文）并生成字幕：
    azure_speech_to_text.py -i ~/speechcli/audio -l zh-CN --srt --vtt
  英文识别并只要 TXT：
    azure_speech_to_text.py -i ~/speechcli/audio/file.wav -l en-US --txt
环境变量：
  SPEECH_KEY（必需）、SPEECH_REGION 或 SPEECH_ENDPOINT（二选一，推荐 REGION）
"""
import os, sys, time, argparse, glob
import azure.cognitiveservices.speech as speechsdk

AUDIO_EXT = {".wav", ".mp3", ".mp4", ".m4a", ".wma", ".ogg", ".flac", ".aac"}

def sec_to_srt(t: float) -> str:
    h=int(t//3600); m=int((t%3600)//60); s=int(t%60); ms=int(round((t-int(t))*1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def sec_to_vtt(t: float) -> str:
    h=int(t//3600); m=int((t%3600)//60); sec=(t%60)
    return f"{h:02d}:{m:02d}:{sec:06.3f}"

def transcribe_one(audio_path: str, lang: str, outdir: str,
                   want_txt: bool, want_tsv: bool, want_srt: bool, want_vtt: bool) -> None:
    audio_path = os.path.expanduser(audio_path)
    base = os.path.splitext(os.path.basename(audio_path))[0]
    os.makedirs(outdir, exist_ok=True)

    # 读取凭据：优先 Region，其次 Endpoint
    speech_key = os.environ.get("SPEECH_KEY")
    speech_region = os.environ.get("SPEECH_REGION")
    speech_endpoint = os.environ.get("SPEECH_ENDPOINT")
    if not speech_key:
        raise SystemExit("缺少环境变量 SPEECH_KEY")
    if not (speech_region or speech_endpoint):
        raise SystemExit("缺少 SPEECH_REGION 或 SPEECH_ENDPOINT（二选一）")

    if speech_endpoint:
        speech_config = speechsdk.SpeechConfig(subscription=speech_key, endpoint=speech_endpoint)
    else:
        speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)

    speech_config.speech_recognition_language = lang
    speech_config.output_format = speechsdk.OutputFormat.Detailed  # 便于拿时间戳
    audio_config = speechsdk.audio.AudioConfig(filename=audio_path)
    recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)

    segments, done = [], False

    def on_recognized(evt):
        res = evt.result
        if res.reason == speechsdk.ResultReason.RecognizedSpeech and res.text:
            start = res.offset / 10_000_000
            end = start + (res.duration / 10_000_000)
            segments.append({"start": start, "end": end, "text": res.text})

    def stop_cb(_):
        nonlocal done
        done = True

    recognizer.recognized.connect(on_recognized)
    recognizer.session_stopped.connect(stop_cb)
    recognizer.canceled.connect(stop_cb)

    print(f"[STT] {audio_path}  →  {outdir}  (lang={lang})")
    recognizer.start_continuous_recognition()
    while not done:
        time.sleep(0.2)
    recognizer.stop_continuous_recognition()

    if not segments:
        print(f"[WARN] 识别结果为空：{audio_path}")
        return

    # 输出
    if want_txt:
        p = os.path.join(outdir, f"{base}.txt")
        with open(p, "w", encoding="utf-8") as f:
            for s in segments: f.write(s["text"] + "\n")
        print("  TXT:", p)

    if want_tsv:
        p = os.path.join(outdir, f"{base}.tsv")
        with open(p, "w", encoding="utf-8") as f:
            f.write("start_s\tend_s\ttext\n")
            for s in segments: f.write(f"{s['start']:.2f}\t{s['end']:.2f}\t{s['text']}\n")
        print("  TSV:", p)

    if want_srt:
        p = os.path.join(outdir, f"{base}.srt")
        with open(p, "w", encoding="utf-8") as f:
            for i,s in enumerate(segments,1):
                f.write(f"{i}\n{sec_to_srt(s['start'])} --> {sec_to_srt(s['end'])}\n{s['text']}\n\n")
        print("  SRT:", p)

    if want_vtt:
        p = os.path.join(outdir, f"{base}.vtt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("WEBVTT\n\n")
            for s in segments:
                f.write(f"{sec_to_vtt(s['start'])} --> {sec_to_vtt(s['end'])}\n{s['text']}\n\n")
        print("  VTT:", p)

def collect_inputs(input_path: str):
    ip = os.path.expanduser(input_path)
    if os.path.isdir(ip):
        files = []
        for ext in AUDIO_EXT:
            files += glob.glob(os.path.join(ip, f"*{ext}"))
        return sorted(files)
    else:
        return [ip]

def main():
    ap = argparse.ArgumentParser(description="Azure Speech-to-Text 批量/单文件工具")
    ap.add_argument("-i", "--input", required=True, help="输入文件或目录")
    ap.add_argument("-l", "--lang", default="zh-CN", help="识别语言（默认 zh-CN，如 en-US / fr-CA）")
    ap.add_argument("-o", "--outdir", default="~/speechcli/stt_out", help="输出目录（默认 ~/speechcli/stt_out）")
    ap.add_argument("--txt", action="store_true", help="输出 .txt（逐段文本）")
    ap.add_argument("--tsv", action="store_true", help="输出 .tsv（带时间戳）")
    ap.add_argument("--srt", action="store_true", help="输出 .srt 字幕")
    ap.add_argument("--vtt", action="store_true", help="输出 .vtt 字幕")
    args = ap.parse_args()

    # 若用户没有指定任何格式，则四种格式都导出（TXT/TSV/SRT/VTT）
    no_fmt = not (args.txt or args.tsv or args.srt or args.vtt)
    if no_fmt:
        want_txt = want_tsv = want_srt = want_vtt = True
    else:
        want_txt = args.txt
        want_tsv = args.tsv
        want_srt = args.srt
        want_vtt = args.vtt


    outdir = os.path.expanduser(args.outdir)
    paths = collect_inputs(args.input)
    if not paths:
        print(f"[ERR] 没有找到可处理的音频：{args.input}")
        sys.exit(2)

    for p in paths:
        ext = os.path.splitext(p)[1].lower()
        if ext not in AUDIO_EXT:
            print(f"[SKIP] 不支持的扩展名：{p}")
            continue
        transcribe_one(p, args.lang, outdir, want_txt, want_tsv, want_srt, want_vtt)

if __name__ == "__main__":
    main()

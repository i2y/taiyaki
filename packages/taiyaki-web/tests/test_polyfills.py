"""Tests for SSR polyfills (TextEncoder, TextDecoder, queueMicrotask, MessageChannel)."""

from __future__ import annotations

from taiyaki_web.runtime import JsRuntime


async def test_text_encoder_available():
    rt = JsRuntime()
    assert rt._rt.eval("typeof TextEncoder") == "function"


async def test_text_decoder_available():
    rt = JsRuntime()
    assert rt._rt.eval("typeof TextDecoder") == "function"


async def test_queue_microtask_available():
    rt = JsRuntime()
    assert rt._rt.eval("typeof queueMicrotask") == "function"


async def test_message_channel_available():
    rt = JsRuntime()
    assert rt._rt.eval("typeof MessageChannel") == "function"


async def test_text_encoder_roundtrip():
    rt = JsRuntime()
    result = rt._rt.eval(
        "new TextDecoder().decode(new TextEncoder().encode('hello'))"
    )
    assert result == "hello"


async def test_message_channel_works():
    rt = JsRuntime()
    result = rt._rt.eval("""
        (() => {
            const ch = new MessageChannel();
            let received = null;
            ch.port2.onmessage = (e) => { received = e.data; };
            ch.port1.postMessage('test');
            return typeof ch.port1.postMessage;
        })()
    """)
    assert result == "function"

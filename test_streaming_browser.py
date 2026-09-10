"""Prueba opcional en Chrome con capturas sintéticas y conexiones locales.

Requiere las dependencias de servidor/cliente, aiortc, numpy y playwright.
Ejecutar: python3 test_streaming_browser.py
VIGIA_TEST_CHROME permite indicar el ejecutable de Chrome/Chromium.
Registra FPS medidos; su valor depende del equipo que ejecuta la prueba.
No captura el escritorio ni inyecta entrada física.
"""


def main():
    import threading, time, socket, logging, json, os, shutil, sys
    from unittest.mock import patch
    from PIL import Image
    import numpy as np
    import server
    # Bloquear solo pynput; restaurar TODO sys.modules después de importar
    # aiortc recargaría clases nativas de cryptography y rompería DTLS.
    previous_pynput = sys.modules.get('pynput')
    sys.modules['pynput'] = None
    with patch('shutil.which', return_value=None), patch('subprocess.run'), \
         patch('platform_utils.IS_LINUX', False), \
         patch('traceback.print_exc'):
        import client
    if previous_pynput is None:
        sys.modules.pop('pynput', None)
    else:
        sys.modules['pynput'] = previous_pynput
    from playwright.sync_api import sync_playwright
    logging.getLogger('werkzeug').setLevel(logging.ERROR)

    class SyntheticCapture:
        name='synthetic'
        def __init__(self):
            self.base=np.zeros((1080,1920,4),dtype=np.uint8)
            self.base[:,:,0]=np.arange(1920,dtype=np.uint16)%255
            self.base[:,:,1]=np.arange(1080,dtype=np.uint16)[:,None]%255
            self.base[:,:,3]=255
        def monitor(self): return dict(width=1920,height=1080,left=0,top=0)
        def grab_raw(self):
            arr=self.base.copy()
            x=int(time.monotonic()*200)%1700
            arr[250:450,x:x+180,:3]=255
            return arr.tobytes(),1920,1080,1920*4
        def grab(self, max_age=0):
            data,w,h,stride=self.grab_raw()
            return Image.frombuffer('RGB',(w,h),data,'raw','BGRX',stride,1)
        def close(self): pass

    client.screen_capture.create_capturer=lambda **kw:SyntheticCapture()
    inputs=[]
    client.INPUT_OK=True
    client._procesar_input=lambda data: inputs.append(data)
    probe=socket.socket(); probe.bind(('127.0.0.1',0)); port=probe.getsockname()[1]; probe.close()
    url=f'http://127.0.0.1:{port}'
    threading.Thread(target=lambda: server.socketio.run(server.app,host='127.0.0.1',port=port,allow_unsafe_werkzeug=True,use_reloader=False),daemon=True).start()
    threading.Thread(target=client._asyncio_runner,daemon=True).start()
    time.sleep(0.25)
    client.sio.connect(url,transports=['websocket'])
    threading.Thread(target=client.bucle_capturas,daemon=True).start()
    metrics=[]
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.environ.get('VIGIA_TEST_CHROME') or shutil.which('google-chrome') or shutil.which('chromium'),headless=True,args=['--no-sandbox','--autoplay-policy=no-user-gesture-required'])
        page=browser.new_page(ignore_https_errors=True,viewport={'width':1440,'height':1000})
        page.on('pageerror',lambda err: (errors.append(str(err)),print('JS ERROR',err,flush=True)))
        page.on('console',lambda msg: print('BROWSER',msg.text) if '[WebRTC]' in msg.text else None)
        page.goto(url,wait_until='networkidle')
        page.wait_for_function('Object.keys(students).length === 1')
        sid=page.evaluate('Object.keys(students)[0]')
        for mode in ['control','view']:
            page.evaluate('([sid,mode])=>abrirLiveView(sid,mode)',[sid,mode])
            page.wait_for_function('_webrtcActivo',timeout=15000)
            page.wait_for_timeout(150)
            assert client._webrtc_activo
            for profile in ['light','balanced','quality']:
                page.evaluate('(name)=>{abrirSettings();_applyPreset(name);guardarSettings();}',profile)
                width=client.PRESETS[profile]['live_width']
                page.wait_for_function('(width)=>document.getElementById("liveview-video").videoWidth===width',arg=width,timeout=8000)
                before=client._frame_window._sequence
                page.wait_for_timeout(2500)
                assert client._frame_window._sequence==before, 'JPEG sigue emitiendo mientras WebRTC reproduce'
                result=page.evaluate('''()=>({fps:document.getElementById('liveview-fps').textContent,
                    width:document.getElementById('liveview-video').videoWidth,
                    transport:document.getElementById('liveview-transport').textContent})''')
                result.update(mode=mode,profile=profile)
                metrics.append(result)
                assert client._stream_cfg['webrtc_bitrate']==client.PRESETS[profile]['webrtc_bitrate']
            if mode=='control':
                page.wait_for_function('_dc_kbd?.readyState === "open"')
                page.evaluate('''()=>{_enviarInput({sid:_liveviewSid,type:'mousedown',button:'left',x:200,y:250});
                  _enviarInput({sid:_liveviewSid,type:'mouseup',button:'left',x:200,y:250});}''')
                page.wait_for_timeout(200)
                assert [d['type'] for d in inputs[-2:]]==['mousedown','mouseup'],inputs
            if mode == 'control':
                page.click('#liveview-header button[onclick="abrirSettings()"]')
                assert page.locator('#settings-overlay').evaluate('(el)=>getComputedStyle(el).zIndex') == '950'
                page.keyboard.press('Escape')
                assert page.evaluate('_liveviewSid !== null'), 'Escape en configuración cierra el control'
                page.evaluate('_fallbackJPEG("prueba de recuperación")')
                page.wait_for_function('document.getElementById("liveview-img").src.startsWith("blob:") && !_webrtcActivo')
                page.wait_for_timeout(300)
                assert not client._webrtc_activo and client._en_observacion
            page.evaluate('cerrarLiveView()')
            page.wait_for_timeout(200)
            assert not client._en_observacion
        page.evaluate('(sid)=>{abrirLiveView(sid,"control");cerrarLiveView();abrirLiveView(sid,"view");}',sid)
        page.wait_for_function('_webrtcActivo', timeout=15000)
        page.wait_for_timeout(300)
        assert client._view_options['mode']=='view' and client._webrtc_activo
        page.evaluate('cerrarLiveView()')
        page.wait_for_timeout(150)
        page.evaluate('(sid)=>{students[sid].webrtc=false;abrirLiveView(sid,"control");}',sid)
        page.wait_for_function('document.getElementById("liveview-img").src.startsWith("blob:")')
        for profile in ['light','balanced','quality']:
            page.evaluate('(name)=>{abrirSettings();_applyPreset(name);guardarSettings();}',profile)
            width=client.PRESETS[profile]['live_width']
            page.wait_for_function('(width)=>document.getElementById("liveview-img").naturalWidth===width',arg=width)
            page.wait_for_timeout(2200)
            metrics.append(page.evaluate('''()=>({mode:'JPEG',profile:_cfgPreset,width:document.getElementById('liveview-img').naturalWidth,
              fps:document.getElementById('liveview-fps').textContent})'''))
        page.evaluate('''()=>{window.savedAck=_ackLiveFrame;window.heldAcks=[];
            _ackLiveFrame=data=>{if(data)heldAcks.push(data);};}''')
        page.wait_for_timeout(250)
        count=client._frame_window._sequence
        page.wait_for_timeout(650)
        assert count==client._frame_window._sequence, 'Se acumulan JPEG con receptor parado'
        page.evaluate('''()=>{_ackLiveFrame=savedAck;heldAcks.forEach(_ackLiveFrame);}''')
        page.wait_for_timeout(300)
        assert client._frame_window._sequence>count
        page.evaluate('()=>{abrirSettings();_applyPreset("light");cerrarSettings();abrirSettings();}')
        assert page.input_value('#cfg-live-width')=='1920','Cancelar cambia la configuración activa'
        page.evaluate('cerrarSettings()')
        page.reload(wait_until='networkidle')
        page.wait_for_function('_cfgPreset === "quality"')
        assert not client._en_observacion
        assert not errors,errors
        page.evaluate('abrirSettings()')
        browser.close()
    client.sio.disconnect()
    print('RESULTADOS',json.dumps(metrics,ensure_ascii=False))
    print('PASS: WebRTC view/control, JPEG, perfiles en vivo, pausa/reanudación, clics, cancelar, recarga y sin errores JS')


if __name__ == '__main__':
    main()

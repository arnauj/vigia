import socketio
import time

sio = socketio.Client()

@sio.event
def connect():
    print("Conectado al servidor")
    sio.emit('register', {'name': 'Test Alumno'})

@sio.event
def registered(data):
    print("Registrado:", data)

if __name__ == '__main__':
    try:
        sio.connect('http://localhost:5000')
        time.sleep(2)
        sio.disconnect()
    except Exception as e:
        print("Error:", e)

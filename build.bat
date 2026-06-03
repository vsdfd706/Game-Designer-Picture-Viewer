@echo off
echo Cleaning old build cache...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist GameView.spec del GameView.spec

echo Installing dependencies...
py -m pip install Pillow pyinstaller pyglet PyOpenGL PyOpenGL_accelerate

echo Building EXE...
py -3.11 -m PyInstaller --onefile --noconsole --name GameView ^
    --icon GameView.ico ^
    --hidden-import pyglet ^
    --hidden-import pyglet.gl ^
    --hidden-import pyglet.image ^
    --hidden-import pyglet.window ^
    --hidden-import pyglet.clock ^
    --hidden-import pyglet.text ^
    --hidden-import OpenGL ^
    --hidden-import OpenGL.GL ^
    --hidden-import OpenGL.platform.win32 ^
    --collect-all pyglet ^
    gameview.py

echo Done!
if exist dist\GameView.exe (
    echo SUCCESS: dist\GameView.exe
    explorer dist
) else (
    echo FAILED: check errors above
)
pause

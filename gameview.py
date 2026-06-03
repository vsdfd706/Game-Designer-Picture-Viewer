"""
GameView - GPU-accelerated image viewer for game designers
Renderer : pyglet 2.x native Sprite API (no legacy OpenGL fixed pipeline)
Python 3.14 compatible
"""
import sys, os, threading, ctypes, time
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Pillow required: pip install Pillow"); sys.exit(1)

import pyglet
from pyglet.window import key, mouse
from pyglet.gl import (glEnable, glDisable, glScissor, glColor4f,
                       glBegin, glEnd, glVertex2f, glTexCoord2f,
                       glBindTexture, glLineWidth,
                       GL_SCISSOR_TEST, GL_TEXTURE_2D,
                       GL_QUADS, GL_LINES, GL_LINE_LOOP,
                       GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_REPEAT)

if sys.platform == "win32":
    try:    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except:
        try: ctypes.windll.user32.SetProcessDPIAware()
        except: pass

WIN_W, WIN_H = 1280, 820
PANEL_W      = 220
TOOLBAR_H    = 48
STATUS_H     = 24

SUPPORTED_EXTS = {".png",".jpg",".jpeg",".bmp",".tga",".gif",
                  ".webp",".ico",".dds",".tiff",".tif",".psd"}

C_BG      = (28,  30,  31,  255)
C_TOOLBAR = (33,  35,  37,  255)
C_PANEL   = (35,  37,  39,  255)
C_BORDER  = (58,  61,  63,  255)
C_TEXT    = (197, 201, 204, 255)
C_DIM     = (107, 114, 117, 255)
C_ACCENT  = (122, 158, 181, 255)
C_ACCENT2 = (145, 175, 194, 255)
C_HOVER   = (46,  49,  51,  255)

def build_file_list(folder):
    try:
        return [os.path.join(folder,f) for f in sorted(os.listdir(folder))
                if Path(f).suffix.lower() in SUPPORTED_EXTS]
    except: return []

def pil_to_sprite(pil_img, x=0, y=0):
    rgba = pil_img.convert("RGBA")
    w, h = rgba.size
    raw  = rgba.tobytes()
    data = pyglet.image.ImageData(w, h, "RGBA", raw, pitch=-w*4)
    tex  = data.get_texture()
    return pyglet.sprite.Sprite(tex, x=x, y=y)

def make_checker_tex(sq=16):
    size = sq*2
    img  = Image.new("RGBA",(size,size))
    d    = ImageDraw.Draw(img)
    d.rectangle([0,0,sq-1,sq-1],         fill=(160,160,160,255))
    d.rectangle([sq,sq,size-1,size-1],   fill=(160,160,160,255))
    d.rectangle([sq,0,size-1,sq-1],      fill=(100,100,100,255))
    d.rectangle([0,sq,sq-1,size-1],      fill=(100,100,100,255))
    raw  = img.tobytes()
    data = pyglet.image.ImageData(size,size,"RGBA",raw,pitch=-size*4)
    tex  = data.get_texture()
    glBindTexture(GL_TEXTURE_2D, tex.id)
    glTexCoord2f(0,0)  # dummy to init
    from pyglet.gl import glTexParameteri
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
    return tex

class Viewport:
    def __init__(self): self.zoom=1.0; self.ox=0.0; self.oy=0.0
    def fit(self,iw,ih,cw,ch):
        s=min(cw/iw,ch/ih,1.0); self.zoom=s
        self.ox=(cw-iw*s)/2; self.oy=(ch-ih*s)/2
    def pan(self,dx,dy): self.ox+=dx; self.oy+=dy
    def zoom_at(self,cx,cy,f):
        nz=max(0.01,min(128.0,self.zoom*f))
        self.ox=cx-(cx-self.ox)*(nz/self.zoom)
        self.oy=cy-(cy-self.oy)*(nz/self.zoom)
        self.zoom=nz
    def img_rect(self,iw,ih): return self.ox,self.oy,iw*self.zoom,ih*self.zoom
    def to_img(self,cx,cy): return (cx-self.ox)/self.zoom,(cy-self.oy)/self.zoom

class ImageLoader:
    def __init__(self):
        self.pil_img=None; self.path=""; self.channel="RGBA"
        self.sprite=None; self._pending=None; self._lock=threading.Lock()
    def load(self,path):
        self.path=path
        def _w():
            try:
                img=Image.open(path)
                try: img.seek(0)
                except: pass
                img.load()
                if img.mode not in("RGB","RGBA","L","LA"): img=img.convert("RGBA")
                with self._lock: self._pending=img
            except Exception as e: print(f"Load error:{e}")
        threading.Thread(target=_w,daemon=True).start()
    def poll(self):
        with self._lock:
            if self._pending is None: return False
            img=self._pending; self._pending=None
        self.pil_img=img; self._upload(img); return True
    def _upload(self,img):
        ch=self._ch_img(img)
        if self.sprite: self.sprite.delete()
        self.sprite=pil_to_sprite(ch)
    def set_channel(self,ch):
        self.channel=ch
        if self.pil_img: self._upload(self.pil_img)
    def _ch_img(self,img):
        if self.channel=="RGBA": return img
        idx={"R":0,"G":1,"B":2,"A":3}.get(self.channel,0)
        sp=img.split()
        if idx<len(sp): return sp[idx].convert("RGBA")
        ph=Image.new("RGBA",img.size,(40,40,50,255))
        ImageDraw.Draw(ph).text((10,img.height//2-8),f"No {self.channel} channel",fill=(150,150,170,255))
        return ph
    def pixel(self,ix,iy):
        if not self.pil_img: return None
        w,h=self.pil_img.size
        return self.pil_img.getpixel((ix,iy)) if 0<=ix<w and 0<=iy<h else None
    @property
    def iw(self): return self.pil_img.size[0] if self.pil_img else 0
    @property
    def ih(self): return self.pil_img.size[1] if self.pil_img else 0

class Btn:
    def __init__(self,x,y,w,h,text):
        self.x=x;self.y=y;self.w=w;self.h=h;self.text=text
        self.hovered=False; self.active=False
    def hit(self,mx,my): return self.x<=mx<self.x+self.w and self.y<=my<self.y+self.h

def gl_fill(x,y,w,h,col):
    glColor4f(col[0]/255,col[1]/255,col[2]/255,col[3]/255)
    glBegin(GL_QUADS)
    glVertex2f(x,y);glVertex2f(x+w,y);glVertex2f(x+w,y+h);glVertex2f(x,y+h)
    glEnd()

def gl_hline(x,y,w,col):
    glColor4f(col[0]/255,col[1]/255,col[2]/255,1)
    glBegin(GL_LINES); glVertex2f(x,y); glVertex2f(x+w,y); glEnd()

def gl_vline(x,y,h,col):
    glColor4f(col[0]/255,col[1]/255,col[2]/255,1)
    glBegin(GL_LINES); glVertex2f(x,y); glVertex2f(x,y+h); glEnd()

def gl_outline(x,y,w,h,col):
    glColor4f(col[0]/255,col[1]/255,col[2]/255,1)
    glBegin(GL_LINE_LOOP)
    glVertex2f(x,y);glVertex2f(x+w,y);glVertex2f(x+w,y+h);glVertex2f(x,y+h)
    glEnd()

def txt(text,x,y,col=C_TEXT,size=10,ax="left",ay="baseline",bold=False):
    pyglet.text.Label(str(text),
        font_name=["Microsoft YaHei","Segoe UI","Arial"],
        font_size=size,bold=bold,x=x,y=y,
        anchor_x=ax,anchor_y=ay,color=col).draw()

class GameViewWindow(pyglet.window.Window):
    def __init__(self):
        super().__init__(WIN_W,WIN_H,caption="GameView",resizable=True,vsync=True)
        pyglet.gl.glClearColor(C_BG[0]/255,C_BG[1]/255,C_BG[2]/255,1)
        try:
            base=os.path.dirname(sys.executable if getattr(sys,'frozen',False) else __file__)
            ico=os.path.join(base,"GameView.ico")
            if os.path.exists(ico): self.set_icon(pyglet.image.load(ico))
        except: pass

        self.loader=ImageLoader(); self.vp=Viewport()
        self.checker=make_checker_tex(16)
        self.file_list=[]; self.file_idx=0
        self.status_msg="就绪 — Ctrl+O 打开，或拖放文件到窗口"
        self.show_grid=False
        self._px_coord=self._px_rgba=self._px_hex="—"
        self.picked_hex="#888888"; self.picked_rgb=(136,136,136)
        self._last_click=0.0
        self._build_btns()
        pyglet.clock.schedule_interval(self._tick,1/60)
        if len(sys.argv)>1 and os.path.isfile(sys.argv[1]): self._open(sys.argv[1])

    def _cw(self): return self.width-PANEL_W
    def _ch(self): return self.height-TOOLBAR_H-STATUS_H
    def _cy(self): return STATUS_H

    def _build_btns(self):
        y=TOOLBAR_H-(TOOLBAR_H-28)//2-28; x=8
        def b(t,w=52):
            nonlocal x
            btn=Btn(x,y,w,28,t); x+=w+3; return btn
        self.b_open=b("打开",58); self.b_folder=b("批量",52); x+=4
        self.b_prev=b("◀",30); self.b_next=b("▶",30); x+=4
        self.b_zi=b("放大",44); self.b_zo=b("缩小",44)
        self.b_fit=b("适应",44); self.b_100=b("1:1",36); x+=4
        self.b_grid=b("网格",44); x+=8
        self._ch_btns={}
        for ch,w in [("RGBA",42),("R",24),("G",24),("B",24),("A",24)]:
            self._ch_btns[ch]=b(ch,w)
        self._ch_btns["RGBA"].active=True
        self._btns=[self.b_open,self.b_folder,self.b_prev,self.b_next,
                    self.b_zi,self.b_zo,self.b_fit,self.b_100,self.b_grid
                    ]+list(self._ch_btns.values())

    def _tick(self,dt):
        if self.loader.poll():
            self.vp.fit(self.loader.iw,self.loader.ih,self._cw(),self._ch())
            self.set_caption(f"GameView — {os.path.basename(self.loader.path)}")
            self.status_msg=f"✔  {os.path.basename(self.loader.path)}"

    def on_draw(self):
        self.clear()
        pyglet.gl.glClearColor(C_BG[0]/255,C_BG[1]/255,C_BG[2]/255,1)
        self._draw_canvas()
        self._draw_chrome()

    def _draw_canvas(self):
        sp=self.loader.sprite
        if sp is None: return
        iw,ih=self.loader.iw,self.loader.ih
        ox,oy,sw,sh=self.vp.img_rect(iw,ih)
        glEnable(GL_SCISSOR_TEST)
        glScissor(0,self._cy(),self._cw(),self._ch())
        bx=ox; by=self._cy()+oy
        # Checker
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D,self.checker.id)
        glColor4f(1,1,1,1)
        sq=16; tx=sw/(sq*2); ty=sh/(sq*2)
        glBegin(GL_QUADS)
        glTexCoord2f(0,ty);  glVertex2f(bx,   by)
        glTexCoord2f(tx,ty); glVertex2f(bx+sw,by)
        glTexCoord2f(tx,0);  glVertex2f(bx+sw,by+sh)
        glTexCoord2f(0,0);   glVertex2f(bx,   by+sh)
        glEnd()
        glDisable(GL_TEXTURE_2D)
        # Image
        sp.update(x=bx,y=by,scale_x=sw/iw,scale_y=sh/ih)
        sp.draw()
        gl_outline(bx-1,by-1,sw+2,sh+2,C_BORDER)
        glDisable(GL_SCISSOR_TEST)

    def _draw_chrome(self):
        W,H=self.width,self.height; cw=self._cw()
        # Status
        gl_fill(0,0,W,STATUS_H,C_TOOLBAR)
        gl_hline(0,STATUS_H,W,C_BORDER)
        txt(self.status_msg,10,STATUS_H//2,C_DIM,9,ax="left",ay="center")
        if self._px_hex!="—":
            txt(f"({self._px_coord})  {self._px_rgba}  {self._px_hex}",
                cw-10,STATUS_H//2,C_DIM,9,ax="right",ay="center")
        # Toolbar
        gl_fill(0,H-TOOLBAR_H,W,TOOLBAR_H,C_TOOLBAR)
        gl_hline(0,H-TOOLBAR_H,W,C_BORDER)
        txt(f"{self.vp.zoom*100:.0f}%",cw-10,H-TOOLBAR_H//2,C_ACCENT2,11,ax="right",ay="center")
        for btn in self._btns:
            bg=C_HOVER if(btn.hovered or btn.active) else C_TOOLBAR
            if btn.active: bg=(50,55,60,255)
            bby=H-btn.y-btn.h
            gl_fill(btn.x,bby,btn.w,btn.h,bg)
            col=C_ACCENT2 if btn.hovered else C_TEXT
            txt(btn.text,btn.x+btn.w//2,bby+btn.h//2,col,9,ax="center",ay="center")
        # Panel
        gl_fill(cw,0,PANEL_W,H,C_PANEL)
        gl_vline(cw,0,H,C_BORDER)
        self._draw_panel(cw,H)

    def _draw_panel(self,px,H):
        y=H-TOOLBAR_H-12; loader=self.loader
        def sec(t):
            nonlocal y; y-=6
            txt(t.upper(),px+10,y,C_ACCENT,9,bold=True,ax="left",ay="top")
            y-=14; gl_hline(px+8,y,PANEL_W-16,C_BORDER); y-=8
        def row(k,v,vc=C_TEXT):
            nonlocal y
            txt(k,px+10,y,C_DIM,9,ax="left",ay="top")
            txt(str(v),px+72,y,vc,9,ax="left",ay="top"); y-=15
        sec("文件")
        if loader.path:
            name=os.path.basename(loader.path)
            if len(name)>22: name=name[:19]+"..."
            row("文件名",name)
            try:
                sz=os.path.getsize(loader.path)
                row("大小",f"{sz/1024:.1f} KB" if sz<1048576 else f"{sz/1048576:.2f} MB")
            except: row("大小","—")
            row("格式",Path(loader.path).suffix.upper().lstrip(".")or"?")
        else: row("文件名","—")
        y-=4; sec("图像")
        if loader.pil_img:
            iw,ih=loader.pil_img.size
            row("宽度",f"{iw} px"); row("高度",f"{ih} px")
            row("颜色",loader.pil_img.mode)
            row("位深",{"RGB":"24-bit","RGBA":"32-bit","L":"8-bit","LA":"16-bit"}.get(loader.pil_img.mode,"—"))
        else: row("尺寸","—")
        y-=4; sec("像素")
        row("坐标",self._px_coord); row("RGBA",self._px_rgba); row("HEX",self._px_hex,C_ACCENT2)
        y-=4; sec("拾色器")
        r,g,b=self.picked_rgb; sw_h=36
        gl_fill(px+10,y-sw_h,PANEL_W-20,sw_h,(r,g,b,255))
        gl_outline(px+10,y-sw_h,PANEL_W-20,sw_h,C_BORDER)
        y-=sw_h+6
        txt(self.picked_hex,px+PANEL_W//2,y,C_ACCENT2,11,ax="center",ay="top"); y-=22
        y-=4; sec("导航")
        nav=f"{self.file_idx+1} / {len(self.file_list)}" if self.file_list else "未打开文件"
        txt(nav,px+10,y,C_DIM,10,ax="left",ay="top")

    def on_resize(self,w,h):
        super().on_resize(w,h)
        if self.loader.pil_img:
            self.vp.fit(self.loader.iw,self.loader.ih,self._cw(),self._ch())

    def on_mouse_press(self,mx,my,button,mods):
        if button!=mouse.LEFT: return
        bmy=self.height-my
        for btn in self._btns:
            if btn.hit(mx,bmy): self._btn_click(btn); return
        now=time.time()
        if now-self._last_click<0.3: self._pick(mx,my)
        self._last_click=now

    def on_mouse_drag(self,mx,my,dx,dy,buttons,mods):
        if buttons&mouse.LEFT and mx<self._cw(): self.vp.pan(dx,dy)

    def on_mouse_motion(self,mx,my,dx,dy):
        bmy=self.height-my
        for btn in self._btns: btn.hovered=btn.hit(mx,bmy)
        loader=self.loader
        if loader.pil_img and mx<self._cw() and self._cy()<=my<self._cy()+self._ch():
            ry=my-self._cy()
            ix,iy=self.vp.to_img(mx,ry)
            iy_pil=loader.ih-1-int(iy)
            px=loader.pixel(int(ix),iy_pil)
            if px is not None:
                self._px_coord=f"{int(ix)}, {iy_pil}"
                if isinstance(px,(int,float)):
                    v=int(px); self._px_rgba=f"L={v}"; self._px_hex=f"#{v:02X}{v:02X}{v:02X}"
                elif len(px)>=4:
                    r,g,b,a=px[:4]; self._px_rgba=f"{r},{g},{b},{a}"; self._px_hex=f"#{r:02X}{g:02X}{b:02X}"
                else:
                    r,g,b=px[:3]; self._px_rgba=f"{r},{g},{b}"; self._px_hex=f"#{r:02X}{g:02X}{b:02X}"
            else: self._px_coord=self._px_rgba=self._px_hex="—"
        else: self._px_coord=self._px_rgba=self._px_hex="—"

    def on_mouse_scroll(self,mx,my,sx,sy):
        if mx<self._cw():
            self.vp.zoom_at(mx,my-self._cy(),1.12 if sy>0 else 1/1.12)
            self.status_msg=f"缩放 {self.vp.zoom*100:.0f}%"

    def on_key_press(self,sym,mods):
        if sym==key.ESCAPE: self.close()
        elif sym==key.O and mods&key.MOD_CTRL: self._open_dialog()
        elif sym in(key.RIGHT,key.DOWN): self._next()
        elif sym in(key.LEFT,key.UP): self._prev()
        elif sym in(key.PLUS,key.EQUAL): self._zoom(1.5)
        elif sym==key.MINUS: self._zoom(1/1.5)
        elif sym==key.F: self._fit()
        elif sym==key._1: self._zoom1()
        elif sym==key.G: self._toggle_grid()

    def on_file_drop(self,x,y,paths):
        if paths: self._open(str(paths[0]))

    def _btn_click(self,b):
        if b==self.b_open: self._open_dialog()
        elif b==self.b_folder: self._folder_dialog()
        elif b==self.b_prev: self._prev()
        elif b==self.b_next: self._next()
        elif b==self.b_zi: self._zoom(1.5)
        elif b==self.b_zo: self._zoom(1/1.5)
        elif b==self.b_fit: self._fit()
        elif b==self.b_100: self._zoom1()
        elif b==self.b_grid: self._toggle_grid()
        elif b in self._ch_btns.values():
            ch=[k for k,v in self._ch_btns.items() if v==b][0]
            for v in self._ch_btns.values(): v.active=False
            b.active=True; self.loader.set_channel(ch)

    def _open_dialog(self):
        try:
            import tkinter as tk; from tkinter import filedialog
            r=tk.Tk(); r.withdraw()
            p=filedialog.askopenfilename(filetypes=[
                ("图像","*.png *.jpg *.jpeg *.bmp *.tga *.dds *.gif *.webp *.ico *.tiff *.tif *.psd"),("所有","*.*")])
            r.destroy()
            if p: self._open(p)
        except Exception as e: self.status_msg=f"错误:{e}"

    def _folder_dialog(self):
        try:
            import tkinter as tk; from tkinter import filedialog
            r=tk.Tk(); r.withdraw(); folder=filedialog.askdirectory(); r.destroy()
            if folder:
                self.file_list=build_file_list(folder)
                if self.file_list: self.file_idx=0; self._open(self.file_list[0])
        except Exception as e: self.status_msg=f"错误:{e}"

    def _open(self,path):
        path=str(path); folder=os.path.dirname(path)
        if not self.file_list or os.path.dirname(self.file_list[0])!=folder:
            self.file_list=build_file_list(folder)
        if path in self.file_list: self.file_idx=self.file_list.index(path)
        self.status_msg=f"加载中… {os.path.basename(path)}"
        self.loader.load(path)

    def _next(self):
        if not self.file_list: return
        self.file_idx=(self.file_idx+1)%len(self.file_list); self._open(self.file_list[self.file_idx])

    def _prev(self):
        if not self.file_list: return
        self.file_idx=(self.file_idx-1)%len(self.file_list); self._open(self.file_list[self.file_idx])

    def _zoom(self,f): self.vp.zoom_at(self._cw()//2,self._ch()//2,f)
    def _fit(self):
        if self.loader.pil_img: self.vp.fit(self.loader.iw,self.loader.ih,self._cw(),self._ch())
    def _zoom1(self):
        if self.loader.pil_img:
            self.vp.zoom=1.0; self.vp.ox=(self._cw()-self.loader.iw)/2; self.vp.oy=(self._ch()-self.loader.ih)/2
    def _toggle_grid(self): self.show_grid=not self.show_grid; self.b_grid.active=self.show_grid
    def _pick(self,mx,my):
        loader=self.loader
        if not loader.pil_img: return
        ix,iy=self.vp.to_img(mx,my-self._cy())
        px=loader.pixel(int(ix),loader.ih-1-int(iy))
        if px is None: return
        if isinstance(px,(int,float)): r=g=b=int(px)
        else: r,g,b=px[0],px[1],px[2]
        self.picked_hex=f"#{r:02X}{g:02X}{b:02X}"; self.picked_rgb=(r,g,b)
        try:
            from tkinter import Tk
            root=Tk(); root.withdraw()
            root.clipboard_clear(); root.clipboard_append(self.picked_hex)
            root.after(200,root.destroy); root.mainloop()
        except: pass
        self.status_msg=f"已拾色并复制:{self.picked_hex}"

if __name__=="__main__":
    win=GameViewWindow()
    pyglet.app.run()

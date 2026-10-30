"""Chinese desktop front end; camera operations only on explicit install/restore."""
import json, os, queue, subprocess, sys, threading, tkinter as tk, winsound
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

ROOT=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
CFG=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))

class App:
    def __init__(self,root):
        self.root=root;root.title('快门声音 · ZV-E10 II');root.geometry('820x680');root.minsize(760,650)
        root.configure(bg='#f4f6f8');self.q=queue.Queue();self.busy=False;self.prepared=None;self.buttons=[]
        style=ttk.Style();style.theme_use('clam');style.configure('.',font=('Microsoft YaHei UI',10))
        style.configure('TFrame',background='#f4f6f8');style.configure('TLabel',background='#f4f6f8')
        style.configure('Title.TLabel',font=('Microsoft YaHei UI',23,'bold'),foreground='#182b43')
        style.configure('TButton',padding=(13,9));style.configure('Accent.TButton',background='#245ad7',foreground='white')
        frame=ttk.Frame(root,padding=26);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='把喜欢的声音，变成快门声',style='Title.TLabel').pack(anchor='w')
        ttk.Label(frame,text='ZV-E10M2 · 固件 1.02 · 此电脑专用 · v0.2',foreground='#59687b').pack(anchor='w',pady=(6,22))
        ttk.Label(frame,text='1   选择音频',font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w')
        row=ttk.Frame(frame);row.pack(fill='x',pady=9)
        self.source=tk.StringVar(value='尚未选择音频')
        ttk.Entry(row,textvariable=self.source,state='readonly').pack(side='left',fill='x',expand=True,padx=(0,8))
        self.button(row,'选择文件',self.choose).pack(side='left')
        ttk.Label(frame,text='支持 MP3 / M4A / WAV / FLAC。完整保留音频，不自动截短。',foreground='#59687b').pack(anchor='w')
        ttk.Label(frame,text='当前容量上限：0.620 秒（沿用已验证的缓冲范围）。',foreground='#59687b').pack(anchor='w',pady=(2,10))
        row=ttk.Frame(frame);row.pack(fill='x')
        ttk.Label(row,text='音量').pack(side='left');self.gain=tk.IntVar(value=100)
        self.volume=ttk.Spinbox(row,from_=10,to=100,increment=5,textvariable=self.gain,width=5);self.volume.pack(side='left',padx=8)
        ttk.Label(row,text='%').pack(side='left')
        self.button(row,'生成并检查',self.prepare,'Accent.TButton').pack(side='left',padx=(18,8))
        self.preview_button=self.button(row,'试听处理后声音',self.preview);self.preview_button.pack(side='left');self.preview_button.configure(state='disabled')
        self.info=tk.StringVar(value='先选择文件，再生成可试听的相机音频。')
        ttk.Label(frame,textvariable=self.info,foreground='#245ad7',wraplength=740).pack(anchor='w',pady=(10,16))
        ttk.Separator(frame).pack(fill='x',pady=(0,16))
        ttk.Label(frame,text='2   写入相机',font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w')
        ttk.Label(frame,text='相机开机 → USB 海量存储器 → 接好数据线。每次操作结束后需重新启动连接。',wraplength=740).pack(anchor='w',pady=(8,4))
        self.power=tk.BooleanVar();ttk.Checkbutton(frame,text='我已确认相机电量超过 50%',variable=self.power).pack(anchor='w')
        row=ttk.Frame(frame);row.pack(fill='x',pady=10)
        self.button(row,'检测 USB 连接',lambda:self.start(['detect'])).pack(side='left',padx=(0,8))
        self.write_button=self.button(row,'备份并写入',self.install,'Accent.TButton');self.write_button.pack(side='left',padx=(0,8));self.write_button.configure(state='disabled')
        self.button(row,'恢复上一版声音',self.restore).pack(side='left',padx=(0,8))
        self.button(row,'恢复原厂声音',self.factory).pack(side='left')
        ttk.Label(frame,text='写入会更新快门加载程序；不会修改 FL2／FL3。断电或写入故障可能导致无法开机。',foreground='#855321',wraplength=740).pack(anchor='w')
        ttk.Label(frame,text='本工具的新换音流程已做电脑模拟检查，尚未完成真机验证。恢复需相机仍能连接。',foreground='#855321',wraplength=740).pack(anchor='w',pady=(3,10))
        self.progress=ttk.Progressbar(frame,mode='indeterminate');self.progress.pack(fill='x')
        self.log=tk.Text(frame,height=7,wrap='word',font=('Microsoft YaHei UI',9),bg='white',relief='flat',state='disabled')
        self.log.pack(fill='both',expand=True,pady=(8,0))
        self.append('准备好后可离线生成、试听。打开工具不会连接或改写相机。')
        self.gain.trace_add('write',self.changed_gain)
        root.after(100,self.poll);root.protocol('WM_DELETE_WINDOW',self.close)
    def button(self,parent,text,fn,style='TButton'):
        b=ttk.Button(parent,text=text,command=fn,style=style);self.buttons.append(b);return b
    def append(self,text):
        self.log.configure(state='normal');self.log.insert('end',text+'\n');self.log.see('end');self.log.configure(state='disabled')
    def choose(self):
        p=filedialog.askopenfilename(title='选择快门音频',filetypes=[('音频','*.mp3 *.m4a *.wav *.flac *.aac *.ogg'),('所有文件','*.*')])
        if p:self.source.set(p);self.prepared=None;self.refresh();self.info.set('文件已选好，点击“生成并检查”。')
    def refresh(self):
        for b in self.buttons:b.configure(state='disabled' if self.busy else 'normal')
        self.volume.configure(state='disabled' if self.busy else 'normal')
        if self.busy or not self.prepared:
            self.preview_button.configure(state='disabled');self.write_button.configure(state='disabled')
    def prepare(self):
        if not Path(self.source.get()).is_file():messagebox.showinfo('选择音频','请先选择一个音频文件。');return
        try:g=self.gain.get()/100
        except Exception:messagebox.showerror('音量','请输入 10 至 100 的音量。');return
        self.prepared=None;self.start(['prepare',self.source.get(),'--gain',str(g)])
    def changed_gain(self,*args):
        if not self.busy and self.prepared:
            self.prepared=None;self.info.set('音量已改变，请重新点击“生成并检查”。');self.refresh()
    def preview(self):
        state=json.loads(Path(self.prepared).read_text(encoding='utf-8'))
        winsound.PlaySound(state['preview'],winsound.SND_FILENAME|winsound.SND_ASYNC)
    def confirm(self,action):
        if not self.power.get():messagebox.showinfo('电量','请确认电量超过 50%，再勾选电量确认。');return False
        return messagebox.askokcancel(action,'将自动核对相机并保存备份，然后'+action+'。\n\n操作期间请保持供电和 USB 连接。新工具的换音流程尚未完成真机验证。\n\n是否开始？')
    def install(self):
        if self.prepared and self.confirm('写入所选声音'):self.start(['install',self.prepared,'--power-confirmed'])
    def restore(self):
        if not (ROOT/'previous.json').exists():messagebox.showinfo('恢复','还没有用本工具替换过声音，没有上一版需要恢复。');return
        if self.confirm('恢复上一版声音'):self.start(['restore','--power-confirmed'])
    def factory(self):
        if not self.power.get():messagebox.showinfo('电量','请确认电量超过 50%，再勾选电量确认。');return
        if messagebox.askokcancel('恢复原厂声音','将备份当前版本，停用自定义完整快门音，并恢复原厂快门声音和原厂加载程序。\n\nFL2／FL3 和其他相机设置保持不变。恢复成功后仍可用“恢复上一版声音”切回此次备份的声音。\n\n需要相机能正常连接；新恢复流程尚未完成真机验证。操作中请勿断电或拔线。\n\n是否开始恢复原厂声音？'):
            self.start(['factory','--power-confirmed'])
    def start(self,args):
        if self.busy:return
        self.busy=True;self.refresh();self.progress.start(12)
        def job():
            try:
                env=os.environ.copy();env['PYTHONIOENCODING']='utf-8'
                p=subprocess.Popen([CFG['python'],'-u',str(ROOT/'backend.py'),*args],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',env=env,creationflags=0x08000000)
                for line in p.stdout:self.q.put(('line',line.rstrip()))
                self.q.put(('done',p.wait()))
            except Exception as e:self.q.put(('line',str(e)));self.q.put(('done',1))
        threading.Thread(target=job,daemon=True).start()
    def poll(self):
        while not self.q.empty():
            kind,value=self.q.get()
            if kind=='line':
                if value.startswith('PREPARED '):
                    self.prepared=value[9:];s=json.loads(Path(self.prepared).read_text(encoding='utf-8'))
                    self.info.set(f"{s['name']}  ·  {s['seconds']:.3f} 秒  ·  音量 {s['gain']:.0%}  ·  完整音频已准备好")
                    self.append('加载配置检查通过，可以试听。')
                else:self.append(value)
            else:
                self.busy=False;self.progress.stop();self.refresh()
                if value:self.append('操作停止。请查看上面的原因；工具不会自动重试写入。')
        self.root.after(100,self.poll)
    def close(self):
        if self.busy:messagebox.showinfo('正在处理','请等待当前操作结束，写入期间不能关闭工具。');return
        winsound.PlaySound(None,0);self.root.destroy()

if __name__=='__main__':
    app=tk.Tk();App(app);app.mainloop()

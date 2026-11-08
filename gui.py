"""Chinese desktop front end; camera operations only on explicit install/restore."""
import json, os, queue, subprocess, sys, threading, tkinter as tk, winsound
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
from filters.apply_offline import apply_profiles

ROOT=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
CFG=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))

class App:
    def __init__(self,root):
        self.root=root;root.title('快门声音 · ZV-E10 II');root.geometry('820x620');root.minsize(760,600)
        root.configure(bg='#f4f6f8');self.q=queue.Queue();self.busy=False;self.prepared=None;self.buttons=[]
        style=ttk.Style();style.theme_use('clam');style.configure('.',font=('Microsoft YaHei UI',10))
        style.configure('TFrame',background='#f4f6f8');style.configure('TLabel',background='#f4f6f8')
        style.configure('Title.TLabel',font=('Microsoft YaHei UI',23,'bold'),foreground='#182b43')
        style.configure('TButton',padding=(13,9));style.configure('Accent.TButton',background='#245ad7',foreground='white')
        frame=ttk.Frame(root,padding=26);frame.pack(fill='both',expand=True)
        heading=ttk.Frame(frame);heading.pack(fill='x')
        ttk.Label(heading,text='把喜欢的声音，变成快门声',style='Title.TLabel').pack(side='left')
        self.button(heading,'FL2／FL3 外观',self.open_filters).pack(side='right')
        ttk.Label(frame,text='ZV-E10M2 · 固件 1.02 · v0.3.4',foreground='#59687b').pack(anchor='w',pady=(6,22))
        ttk.Label(frame,text='1   选择音频',font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w')
        row=ttk.Frame(frame);row.pack(fill='x',pady=9)
        self.source=tk.StringVar(value='尚未选择音频')
        ttk.Entry(row,textvariable=self.source,state='readonly').pack(side='left',fill='x',expand=True,padx=(0,8))
        self.button(row,'选择文件',self.choose).pack(side='left')
        ttk.Label(frame,text='MP3 / M4A / WAV / FLAC · 最长 0.620 秒',foreground='#59687b').pack(anchor='w',pady=(0,10))
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
        ttk.Label(frame,text='连接相机后，选择 USB 海量存储器。',wraplength=740).pack(anchor='w',pady=(8,4))
        self.power=tk.BooleanVar();ttk.Checkbutton(frame,text='我已确认相机电量超过 50%',variable=self.power).pack(anchor='w')
        row=ttk.Frame(frame);row.pack(fill='x',pady=10)
        self.button(row,'检测 USB 连接',lambda:self.start(['detect'])).pack(side='left',padx=(0,8))
        self.write_button=self.button(row,'备份并写入',self.install,'Accent.TButton');self.write_button.pack(side='left',padx=(0,8));self.write_button.configure(state='disabled')
        self.button(row,'恢复上一版声音',self.restore).pack(side='left',padx=(0,8))
        self.button(row,'恢复原厂声音',self.factory).pack(side='left')
        self.progress=ttk.Progressbar(frame,mode='indeterminate');self.progress.pack(fill='x')
        self.log=tk.Text(frame,height=7,wrap='word',font=('Microsoft YaHei UI',9),bg='white',relief='flat',state='disabled')
        self.result=tk.StringVar()
        status=ttk.Frame(frame);status.pack(fill='x',pady=(8,0))
        ttk.Label(status,textvariable=self.result,wraplength=570).pack(side='left',fill='x',expand=True)
        self.details=ttk.Button(status,text='详细日志',command=self.toggle_details)
        self.details.pack(side='right')
        self.error=None
        self.gain.trace_add('write',self.changed_gain)
        root.after(100,self.poll);root.protocol('WM_DELETE_WINDOW',self.close)
    def button(self,parent,text,fn,style='TButton'):
        b=ttk.Button(parent,text=text,command=fn,style=style);self.buttons.append(b);return b
    def toggle_details(self):
        if self.log.winfo_manager():
            self.log.pack_forget()
            self.details.configure(text='详细日志')
            self.root.geometry('820x620')
        else:
            self.log.pack(fill='both',expand=True,pady=(8,0))
            self.details.configure(text='收起日志')
            self.root.geometry('820x750')
            self.log.see('end')
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
    def confirm(self,action,parent=None):
        if not self.power.get():messagebox.showinfo('电量','请确认电量超过 50%，再勾选电量确认。',parent=parent);return False
        return messagebox.askokcancel(action,'将自动核对相机并保存备份，然后'+action+'。\n\n操作期间请保持供电和 USB 连接。\n\n是否开始？',parent=parent)
    def install(self):
        if self.prepared and self.confirm('写入所选声音'):self.start(['install',self.prepared,'--power-confirmed'])
    def restore(self):
        if not (ROOT/'previous.json').exists():messagebox.showinfo('恢复','还没有用本工具替换过声音，没有上一版需要恢复。');return
        if self.confirm('恢复上一版声音'):self.start(['restore','--power-confirmed'])
    def factory(self):
        if not self.power.get():messagebox.showinfo('电量','请确认电量超过 50%，再勾选电量确认。');return
        if messagebox.askokcancel('恢复原厂声音','将备份当前版本，停用自定义完整快门音，并恢复原厂快门声音和原厂加载程序。\n\nFL2／FL3 和其他相机设置保持不变。恢复成功后仍可用“恢复上一版声音”切回此次备份的声音。\n\n需要相机能正常连接。操作中请勿断电或拔线。\n\n是否开始恢复原厂声音？'):
            self.start(['factory','--power-confirmed'])
    def open_filters(self):
        dialog=tk.Toplevel(self.root)
        dialog.title('FL2／FL3 外观')
        dialog.transient(self.root)
        dialog.resizable(False,False)
        frame=ttk.Frame(dialog,padding=22)
        frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='从匹配的 ZV-E10M2 1.02 备份生成外观文件',font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w')
        ttk.Label(frame,text='在电脑上离线生成。选择包含三份原始文件的目录。').pack(anchor='w',pady=(6,12))
        ttk.Label(frame,text='cpapp-b.bin · unit-02a40001.bin · unit-02a4000d.bin').pack(anchor='w')
        originals=ROOT/'filter_originals'
        source=tk.StringVar(master=dialog,value=str(originals) if originals.is_dir() else '')
        parent=tk.StringVar(master=dialog)
        for label,value in (('原始备份目录',source),('输出位置',parent)):
            ttk.Label(frame,text=label).pack(anchor='w',pady=(12,3))
            row=ttk.Frame(frame)
            row.pack(fill='x')
            ttk.Entry(row,textvariable=value,width=58,state='readonly').pack(side='left',fill='x',expand=True)
            def choose_directory(variable=value,title=label):
                directory=filedialog.askdirectory(parent=dialog,title=title,mustexist=True)
                if directory:
                    variable.set(directory)
            ttk.Button(row,text='选择目录',command=choose_directory).pack(side='left',padx=(8,0))

        choice=tk.StringVar(master=dialog,value='FL2 + FL3')
        ttk.Label(frame,text='生成外观').pack(anchor='w',pady=(12,3))
        ttk.Combobox(frame,textvariable=choice,values=('FL2 + FL3','FL2','FL3'),state='readonly',width=14).pack(anchor='w')
        ttk.Label(frame,text='将在输出位置新建外观目录。').pack(anchor='w',pady=(6,10))

        def generate():
            if not source.get() or not parent.get():
                messagebox.showinfo('选择目录','请选择原始备份目录和输出位置。',parent=dialog)
                return
            looks=('FL2','FL3') if choice.get()=='FL2 + FL3' else (choice.get(),)
            output=Path(parent.get())/('ZVE10M2-'+'-'.join(looks))
            if output.exists():
                messagebox.showerror('目录已存在','请另选一个输出位置。',parent=dialog)
                return
            input_path=Path(source.get())
            dialog.destroy()
            self.start(['filters',str(input_path),str(output),*looks])

        actions=ttk.Frame(frame)
        actions.pack(fill='x')
        ttk.Button(actions,text='生成外观文件',command=generate).pack(side='left')

        def import_camera():
            if not self.power.get():
                messagebox.showinfo('电量确认','请在主窗口勾选相机电量超过 50%。',parent=dialog)
                return
            if messagebox.askokcancel(
                    '导入相机',
                    '将一起导入 FL2／FL3，分别用于 IN／SH。请将相机以 USB 海量存储器模式连接。\n\n工具会先核对并备份相机，写入时请保持供电和连接。',
                    parent=dialog):
                dialog.destroy()
                self.start(['install-filters','--power-confirmed'])

        ttk.Button(actions,text='导入两套到相机',command=import_camera,style='Accent.TButton').pack(side='right')
        ttk.Separator(frame).pack(fill='x',pady=12)
        ttk.Label(frame,text='相机左侧图标',font=('Microsoft YaHei UI',11,'bold')).pack(anchor='w')
        ttk.Label(frame,text='检查两套显示资源，再按需更新原 IN／SH 图标。').pack(anchor='w',pady=(4,8))
        icon_actions=ttk.Frame(frame)
        icon_actions.pack(fill='x')

        def check_icons():
            dialog.destroy()
            self.start(['check-icons'])

        def update_icons():
            if self.confirm('更新 FL2／FL3 图标',parent=dialog):
                dialog.destroy()
                self.start(['install-icons','--power-confirmed'])

        ttk.Button(icon_actions,text='检查相机图标',command=check_icons).pack(side='left')
        ttk.Button(icon_actions,text='更新相机图标',command=update_icons,style='Accent.TButton').pack(side='right')
        dialog.grab_set()
        dialog.focus_set()

    def start(self,args):
        if self.busy:return
        self.busy=True;self.error=None;self.result.set('正在处理…');self.refresh();self.progress.start(12)
        def job():
            try:
                if args[0]=='filters':
                    output=Path(args[2])
                    apply_profiles(Path(args[1]),output,tuple(args[3:]))
                    self.q.put(('line',f'外观文件已生成：{output}'))
                    self.q.put(('done',0))
                    return
                env=os.environ.copy();env['PYTHONIOENCODING']='utf-8'
                p=subprocess.Popen([CFG['python'],'-u',str(ROOT/'backend.py'),*args],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',env=env,creationflags=0x08000000)
                for line in p.stdout:self.q.put(('line',line.rstrip()))
                self.q.put(('done',p.wait()))
            except Exception as e:self.q.put(('line','未完成：'+str(e)));self.q.put(('done',1))
        threading.Thread(target=job,daemon=True).start()
    def poll(self):
        while not self.q.empty():
            kind,value=self.q.get()
            if kind=='line':
                if value.startswith('PREPARED '):
                    self.prepared=value[9:];s=json.loads(Path(self.prepared).read_text(encoding='utf-8'))
                    self.info.set(f"{s['name']}  ·  {s['seconds']:.3f} 秒  ·  音量 {s['gain']:.0%}  ·  完整音频已准备好")
                    self.append('加载配置检查通过，可以试听。')
                else:
                    self.append(value)
                    if value.startswith('未完成：'):
                        self.error=value
                    elif value.startswith(('检测到 Sony USB','未检测到 Sony USB')):
                        self.result.set(value.split('；',1)[0])
                    elif value.startswith(('外观文件已生成：','FL2／FL3 已导入','相机已安装 FL2／FL3')):
                        self.result.set(value)
                    elif value.startswith(('图标资源：','相机图标资源已更新','图标更新和回读通过','正在更新并回读图标')):
                        self.result.set(value)
                    elif value.startswith('写入并回读成功'):
                        self.result.set('写入成功。拔线关机，等指示灯熄灭后取电池一分钟，再开机试听。')
            else:
                self.busy=False;self.progress.stop();self.refresh()
                if value:
                    self.result.set(self.error or '操作未完成，请查看详细日志。')
                elif self.result.get()=='正在处理…':
                    self.result.set('已完成。')
        self.root.after(100,self.poll)
    def close(self):
        if self.busy:messagebox.showinfo('正在处理','请等待当前操作结束，写入期间不能关闭工具。');return
        winsound.PlaySound(None,0);self.root.destroy()

if __name__=='__main__':
    app=tk.Tk();App(app);app.mainloop()

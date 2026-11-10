"""Chinese desktop front end; camera operations only on explicit install/restore."""
import json, os, queue, subprocess, sys, threading, tkinter as tk, winsound
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
from filters.apply_offline import apply_profiles
from filters.cube_converter import BUILTIN_LUT_LABELS, ensure_sample_cube_files
from filters.icon_builder import ICON_PRESETS, validate_icon_word

ROOT=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
CFG=json.loads((ROOT/'config.json').read_text(encoding='utf-8')) if (ROOT/'config.json').is_file() else json.loads((ROOT/'config.example.json').read_text(encoding='utf-8'))
ASSETS=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
PAPER='#fff6f5'
SURFACE='#ffffff'
INK='#38232e'
MUTED='#745461'
ACCENT='#9a2146'
HEADER='#45192b'
BLUSH='#ffe8ee'
BORDER='#ecd8de'

class App:
    def __init__(self,root):
        self.root=root;root.title('ZV-E10 II 相机工具');root.geometry('860x650');root.minsize(770,620)
        root.configure(bg=PAPER);self.q=queue.Queue();self.busy=False;self.prepared=None;self.buttons=[]
        self.configure_styles()
        frame=ttk.Frame(root,padding=20);frame.pack(fill='both',expand=True)

        heading=ttk.Frame(frame,style='Header.TFrame',padding=(16,13));heading.pack(fill='x')
        icon_path=ASSETS/'android/res/mipmap-xxxhdpi/ic_launcher.png'
        if icon_path.is_file():
            icon=tk.PhotoImage(file=icon_path)
            root.iconphoto(True,icon)
            self.mascot=icon.subsample(4)
            ttk.Label(heading,image=self.mascot,style='Header.TLabel').pack(side='left',padx=(0,12))
        titles=ttk.Frame(heading,style='Header.TFrame');titles.pack(side='left',fill='x',expand=True)
        ttk.Label(titles,text='ZV-E10 II 相机工具',style='Title.TLabel').pack(anchor='w')
        ttk.Label(titles,text='固件 1.02  ·  Windows 0.3.6',style='Header.TLabel').pack(anchor='w')
        self.button(heading,'FL2／FL3 与 LUT 直出',self.open_filters).pack(side='right')

        status=self.card(frame)
        status_row=ttk.Frame(status,style='Card.TFrame');status_row.pack(fill='x')
        status_text=ttk.Frame(status_row,style='Card.TFrame');status_text.pack(side='left',fill='x',expand=True)
        ttk.Label(status_text,text='实时状态',style='Eyebrow.TLabel').pack(anchor='w')
        self.result=tk.StringVar(value='等待操作')
        ttk.Label(status_text,textvariable=self.result,style='Card.TLabel',wraplength=580).pack(anchor='w',pady=(2,0))
        self.details=ttk.Button(status_row,text='详细日志',command=self.toggle_details)
        self.details.pack(side='right',padx=(10,0))
        self.progress=ttk.Progressbar(status,mode='determinate',style='Live.Horizontal.TProgressbar')
        self.progress.pack(fill='x',pady=(8,0))
        self.log_panel=ttk.Frame(status,style='Card.TFrame')
        self.log=tk.Text(self.log_panel,height=7,wrap='word',font=('Microsoft YaHei UI',9),
                         bg=PAPER,fg=INK,relief='flat',padx=10,pady=8,state='disabled')
        scrollbar=ttk.Scrollbar(self.log_panel,orient='vertical',command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.pack(side='left',fill='both',expand=True)
        scrollbar.pack(side='right',fill='y')

        audio=self.card(frame)
        self.section(audio,'01','自定义快门音')
        row=ttk.Frame(audio,style='Card.TFrame');row.pack(fill='x',pady=(10,7))
        self.source=tk.StringVar(value='尚未选择音频')
        ttk.Entry(row,textvariable=self.source,state='readonly').pack(side='left',fill='x',expand=True,padx=(0,8))
        self.button(row,'选择文件',self.choose).pack(side='left')
        ttk.Label(audio,text='MP3 / M4A / WAV / FLAC  ·  最长 0.620 秒',style='Muted.Card.TLabel').pack(anchor='w',pady=(0,8))
        row=ttk.Frame(audio,style='Card.TFrame');row.pack(fill='x')
        ttk.Label(row,text='音量',style='Card.TLabel').pack(side='left');self.gain=tk.IntVar(value=100)
        self.volume=ttk.Spinbox(row,from_=10,to=100,increment=5,textvariable=self.gain,width=5);self.volume.pack(side='left',padx=8)
        ttk.Label(row,text='%',style='Card.TLabel').pack(side='left')
        self.button(row,'生成并检查',self.prepare,'Accent.TButton').pack(side='left',padx=(18,8))
        self.preview_button=self.button(row,'试听处理后声音',self.preview);self.preview_button.pack(side='left');self.preview_button.configure(state='disabled')
        self.info=tk.StringVar(value='先选择文件，再生成可试听的相机音频。')
        ttk.Label(audio,textvariable=self.info,style='Eyebrow.TLabel',wraplength=700).pack(anchor='w',pady=(8,0))

        camera=self.card(frame)
        self.section(camera,'02','写入相机')
        ttk.Label(camera,text='连接相机后，选择 USB 海量存储器。',style='Muted.Card.TLabel').pack(anchor='w',pady=(7,5))
        self.power=tk.BooleanVar();ttk.Checkbutton(camera,text='我已确认相机电量超过 50%',variable=self.power).pack(anchor='w')
        row=ttk.Frame(camera,style='Card.TFrame');row.pack(fill='x',pady=(9,0))
        self.button(row,'检测 USB 连接',lambda:self.start(['detect'])).pack(side='left',padx=(0,8))
        self.write_button=self.button(row,'备份并写入',self.install,'Accent.TButton');self.write_button.pack(side='left',padx=(0,8));self.write_button.configure(state='disabled')
        self.button(row,'恢复上一版声音',self.restore).pack(side='left',padx=(0,8))
        self.button(row,'恢复原厂声音',self.factory).pack(side='left')
        self.error=None
        self.gain.trace_add('write',self.changed_gain)
        root.after(100,self.poll);root.protocol('WM_DELETE_WINDOW',self.close)

    def configure_styles(self):
        style=ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.',font=('Microsoft YaHei UI',10),foreground=INK)
        style.configure('TFrame',background=PAPER)
        style.configure('TLabel',background=PAPER)
        style.configure('Header.TFrame',background=HEADER)
        style.configure('Header.TLabel',background=HEADER,foreground='#ffd2dd')
        style.configure('Title.TLabel',font=('Microsoft YaHei UI',20,'bold'),background=HEADER,foreground=SURFACE)
        style.configure('Card.TFrame',background=SURFACE,relief='flat',borderwidth=0)
        style.configure('Panel.TFrame',background=SURFACE,bordercolor=BORDER,relief='solid')
        style.configure('Card.TLabel',background=SURFACE)
        style.configure('Muted.Card.TLabel',foreground=MUTED)
        style.configure('Section.Card.TLabel',font=('Microsoft YaHei UI',13,'bold'))
        style.configure('Eyebrow.TLabel',background=SURFACE,foreground=ACCENT)
        style.configure('Badge.TLabel',background=BLUSH,foreground=ACCENT,padding=(7,3),font=('Microsoft YaHei UI',9,'bold'))
        style.configure('TCheckbutton',background=SURFACE)
        style.map('TCheckbutton',background=[('active',SURFACE)])
        style.configure('TButton',padding=(13,7),background=BLUSH,bordercolor=BORDER,foreground=HEADER)
        style.map('TButton',background=[('disabled','#f0e9eb'),('pressed','#edc7d3'),('active','#f8dce5')],
                  foreground=[('disabled','#836b75')])
        style.configure('Accent.TButton',background=ACCENT,foreground=SURFACE,bordercolor=ACCENT)
        style.map('Accent.TButton',background=[('disabled','#f0e9eb'),('pressed','#711633'),('active','#ad2d54')],
                  foreground=[('disabled','#836b75'),('!disabled',SURFACE)])
        style.configure('TEntry',padding=6,fieldbackground=PAPER,bordercolor=BORDER)
        style.map('TEntry',fieldbackground=[('readonly',PAPER)])
        style.configure('TSpinbox',padding=4,fieldbackground=PAPER,bordercolor=BORDER)
        style.configure('TCombobox',padding=4,fieldbackground=PAPER,bordercolor=BORDER)
        style.configure('Live.Horizontal.TProgressbar',background=ACCENT,troughcolor=BLUSH,
                        bordercolor=BLUSH,lightcolor=ACCENT,darkcolor=ACCENT,thickness=6)

    def card(self,parent):
        frame=ttk.Frame(parent,style='Panel.TFrame',padding=(16,12),borderwidth=1)
        frame.pack(fill='x',pady=(10,0))
        return frame

    def section(self,parent,number,title):
        row=ttk.Frame(parent,style='Card.TFrame')
        row.pack(fill='x')
        ttk.Label(row,text=number,style='Badge.TLabel').pack(side='left',padx=(0,9))
        ttk.Label(row,text=title,style='Section.Card.TLabel').pack(side='left')

    def button(self,parent,text,fn,style='TButton'):
        b=ttk.Button(parent,text=text,command=fn,style=style);self.buttons.append(b);return b
    def toggle_details(self):
        if self.log_panel.winfo_manager():
            self.log_panel.pack_forget()
            self.details.configure(text='详细日志')
            self.root.geometry(f'{self.root.winfo_width()}x{self.log_closed_height}')
        else:
            self.log_closed_height=self.root.winfo_height()
            self.log_panel.pack(fill='x',pady=(8,0))
            self.details.configure(text='收起日志')
            height=min(self.log_closed_height+155,self.root.winfo_screenheight()-90)
            self.root.geometry(f'{self.root.winfo_width()}x{max(height,self.log_closed_height)}')
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
        luts_dir=ROOT/'filters'/'luts'
        fl23_manifest=json.loads((ROOT/'filters/FL2-FL3.json').read_text(encoding='utf-8'))
        ensure_sample_cube_files(luts_dir,fl23_manifest)
        builtin_cubes=sorted(
            luts_dir.glob('*.cube'),
            key=lambda p:(list(BUILTIN_LUT_LABELS).index(p.name) if p.name in BUILTIN_LUT_LABELS else 999,p.name),
        )
        preset_map={'默认（索尼原厂胶片 2 号曲线）':None,'默认（索尼原厂胶片 3 号曲线）':None}
        labeled_items=[]
        for p in builtin_cubes:
            display=BUILTIN_LUT_LABELS.get(p.name,p.stem)
            preset_map[display]=str(p)
            labeled_items.append(display)

        dialog=tk.Toplevel(self.root)
        dialog.title('FL2／FL3 外观与 LUT 直出')
        dialog.transient(self.root)
        dialog.resizable(False,False)
        shell=ttk.Frame(dialog,padding=16)
        shell.pack(fill='both',expand=True)
        heading=ttk.Frame(shell,style='Header.TFrame',padding=(16,11))
        heading.pack(fill='x')
        ttk.Label(heading,text='FL2／FL3 创意外观 · LUT 直出',style='Title.TLabel').pack(anchor='w')
        ttk.Label(heading,text='ZV-E10M2  ·  固件 1.02  ·  支持任意 .cube 3D LUT 拍照/视频直出与图标名称区分',style='Header.TLabel').pack(anchor='w')

        lut_card=self.card(shell)
        self.section(lut_card,'01','LUT 选择（拍照／视频直出槽位配置）')
        ttk.Label(lut_card,text='可保持默认，也可从下拉列表选择 14 款内置中文胶片/电影 LUT，或浏览任意 .cube 文件。',style='Muted.Card.TLabel').pack(anchor='w',pady=(6,4))

        in_options=['默认（索尼原厂胶片 2 号曲线）']+labeled_items
        sh_options=['默认（索尼原厂胶片 3 号曲线）']+labeled_items
        in_lut_var=tk.StringVar(master=dialog,value=in_options[0])
        sh_lut_var=tk.StringVar(master=dialog,value=sh_options[0])

        for slot_title,var,opts in (
            ('IN 槽位（FL2）',in_lut_var,in_options),
            ('SH 槽位（FL3）',sh_lut_var,sh_options),
        ):
            row=ttk.Frame(lut_card,style='Card.TFrame')
            row.pack(fill='x',pady=(5,2))
            ttk.Label(row,text=slot_title,style='Card.TLabel',width=15).pack(side='left')
            combo=ttk.Combobox(row,textvariable=var,values=opts,width=42)
            combo.pack(side='left',fill='x',expand=True,padx=(4,8))
            def browse_cube(target_var=var,target_combo=combo,base_opts=opts):
                path=filedialog.askopenfilename(
                    parent=dialog,
                    title='选择 .cube 3D LUT 文件',
                    initialdir=str(luts_dir) if luts_dir.is_dir() else str(ROOT),
                    filetypes=[('Cube 3D LUT','*.cube'),('所有文件','*.*')],
                )
                if path:
                    target_var.set(path)
                    if path not in base_opts:
                        target_combo.configure(values=[*base_opts,path])
            ttk.Button(row,text='浏览 .cube…',command=browse_cube).pack(side='left')

        def resolve_cube(val):
            v=val.strip()
            if not v or v.startswith('默认'):
                return None
            if v in preset_map:
                return preset_map[v]
            return v

        frame=self.card(shell)
        self.section(frame,'02','离线生成（含直出曲线、16 色相矩阵、CP 3D LUT 与 AP .LUT）')
        ttk.Label(frame,text='选择包含三份原始文件的备份目录（cpapp-b.bin · unit-02a40001.bin · unit-02a4000d.bin）。',style='Muted.Card.TLabel').pack(anchor='w',pady=(6,3))
        originals=ROOT/'filter_originals'
        if not originals.is_dir():
            alt=Path(CFG.get('research','')).parent/'fl23_research/live_colour_20261027_225506_564406'
            if alt.is_dir():originals=alt
        source=tk.StringVar(master=dialog,value=str(originals) if originals.is_dir() else '')
        parent=tk.StringVar(master=dialog)
        for label,value in (('原始备份目录',source),('输出位置',parent)):
            ttk.Label(frame,text=label,style='Card.TLabel').pack(anchor='w',pady=(6,2))
            row=ttk.Frame(frame,style='Card.TFrame')
            row.pack(fill='x')
            ttk.Entry(row,textvariable=value,width=58,state='readonly').pack(side='left',fill='x',expand=True)
            def choose_directory(variable=value,title=label):
                directory=filedialog.askdirectory(parent=dialog,title=title,mustexist=True)
                if directory:
                    variable.set(directory)
            ttk.Button(row,text='选择目录',command=choose_directory).pack(side='left',padx=(8,0))

        choice=tk.StringVar(master=dialog,value='FL2 + FL3')
        actions=ttk.Frame(frame,style='Card.TFrame')
        actions.pack(fill='x',pady=(10,0))
        ttk.Label(actions,text='生成范围',style='Card.TLabel').pack(side='left')
        ttk.Combobox(actions,textvariable=choice,values=('FL2 + FL3','FL2','FL3'),state='readonly',width=11).pack(side='left',padx=8)

        def generate():
            if not source.get() or not parent.get():
                messagebox.showinfo('选择目录','请选择原始备份目录和输出位置。',parent=dialog)
                return
            in_cube=resolve_cube(in_lut_var.get())
            sh_cube=resolve_cube(sh_lut_var.get())
            for p in (in_cube,sh_cube):
                if p and not Path(p).is_file():
                    messagebox.showerror('找不到 LUT 文件',f'找不到所选 .cube 文件：\n{p}',parent=dialog)
                    return
            looks=('FL2','FL3') if choice.get()=='FL2 + FL3' else (choice.get(),)
            suffix='-'.join(looks)
            if in_cube or sh_cube:
                suffix+='-LUT'
            output=Path(parent.get())/('ZVE10M2-'+suffix)
            if output.exists():
                messagebox.showerror('目录已存在','请另选一个输出位置。',parent=dialog)
                return
            input_path=Path(source.get())
            dialog.destroy()
            self.start(['filters',str(input_path),str(output),in_cube or '',sh_cube or '',*looks])

        ttk.Button(actions,text='生成外观与 LUT 直出文件',command=generate,style='Accent.TButton').pack(side='right')
        camera=self.card(shell)
        self.section(camera,'03','相机操作（USB 写入与图标名称区分）')
        ttk.Label(camera,text='可独立设置相机左侧列表「上方带数字 1~6 快捷图标」与「下方无数字基础图标」的代号（1~3 位大写字母/数字），避免上下同名混淆。',style='Muted.Card.TLabel',wraplength=680).pack(anchor='w',pady=(6,6))

        icon_preset_labels=[item[1] for item in ICON_PRESETS]+['自定义代号（在下方输入框自由填写 1~3 位字母/数字）']
        icon_preset_var=tk.StringVar(master=dialog,value=ICON_PRESETS[0][1])
        top_in_var=tk.StringVar(master=dialog,value=ICON_PRESETS[0][2])
        top_sh_var=tk.StringVar(master=dialog,value=ICON_PRESETS[0][3])
        bot_in_var=tk.StringVar(master=dialog,value=ICON_PRESETS[0][4])
        bot_sh_var=tk.StringVar(master=dialog,value=ICON_PRESETS[0][5])
        sync_title_var=tk.BooleanVar(master=dialog,value=True)

        preset_row=ttk.Frame(camera,style='Card.TFrame')
        preset_row.pack(fill='x',pady=(0,6))
        ttk.Label(preset_row,text='图标名称方案',style='Card.TLabel',width=13).pack(side='left')
        preset_combo=ttk.Combobox(preset_row,textvariable=icon_preset_var,values=icon_preset_labels,state='readonly',width=54)
        preset_combo.pack(side='left',fill='x',expand=True,padx=(4,0))

        custom_row=ttk.Frame(camera,style='Card.TFrame')
        custom_row.pack(fill='x',pady=(2,8))
        ttk.Label(custom_row,text='上方 1~6 图标：',style='Card.TLabel').pack(side='left')
        ttk.Entry(custom_row,textvariable=top_in_var,width=5).pack(side='left',padx=(2,2))
        ttk.Label(custom_row,text='/',style='Card.TLabel').pack(side='left')
        ttk.Entry(custom_row,textvariable=top_sh_var,width=5).pack(side='left',padx=(2,14))

        ttk.Label(custom_row,text='下方基础图标：',style='Card.TLabel').pack(side='left')
        ttk.Entry(custom_row,textvariable=bot_in_var,width=5).pack(side='left',padx=(2,2))
        ttk.Label(custom_row,text='/',style='Card.TLabel').pack(side='left')
        ttk.Entry(custom_row,textvariable=bot_sh_var,width=5).pack(side='left',padx=(2,14))

        ttk.Checkbutton(custom_row,text='同步大字标题',variable=sync_title_var).pack(side='left')

        def on_preset_selected(*_):
            selected=icon_preset_var.get()
            for _,label,t_in,t_sh,b_in,b_sh,_,_ in ICON_PRESETS:
                if label==selected:
                    top_in_var.set(t_in)
                    top_sh_var.set(t_sh)
                    bot_in_var.set(b_in)
                    bot_sh_var.set(b_sh)
                    break

        preset_combo.bind('<<ComboboxSelected>>',on_preset_selected)

        def import_camera():
            if not self.power.get():
                messagebox.showinfo('电量确认','请在主窗口勾选相机电量超过 50%。',parent=dialog)
                return
            in_cube=resolve_cube(in_lut_var.get())
            sh_cube=resolve_cube(sh_lut_var.get())
            for p in (in_cube,sh_cube):
                if p and not Path(p).is_file():
                    messagebox.showerror('找不到 LUT 文件',f'找不到所选 .cube 文件：\n{p}',parent=dialog)
                    return
            desc_in=in_lut_var.get() if in_cube else '默认（索尼原厂胶片 2 号曲线）'
            desc_sh=sh_lut_var.get() if sh_cube else '默认（索尼原厂胶片 3 号曲线）'
            if messagebox.askokcancel(
                    '导入到相机（LUT 直出）',
                    f'即将导入创意外观直出配置：\n· IN 槽位（FL2）：{desc_in}\n· SH 槽位（FL3）：{desc_sh}\n\n请将相机以 USB 海量存储器模式连接。\n工具会先执行指令级离线校验并完整备份相机，写入时请保持供电和连接。',
                    parent=dialog):
                dialog.destroy()
                cmd=['install-filters','--power-confirmed']
                if in_cube:cmd.extend(['--in-cube',in_cube])
                if sh_cube:cmd.extend(['--sh-cube',sh_cube])
                self.start(cmd)

        icon_actions=ttk.Frame(camera,style='Card.TFrame')
        icon_actions.pack(fill='x')
        ttk.Button(icon_actions,text='导入所选外观／LUT 到相机',command=import_camera,style='Accent.TButton').pack(side='left',padx=(0,8))

        def check_icons():
            dialog.destroy()
            self.start(['check-icons'])

        def update_icons():
            if not self.power.get():
                messagebox.showinfo('电量','请先在主窗口勾选相机电量超过 50%。',parent=dialog)
                return
            try:
                t_in=validate_icon_word(top_in_var.get(),'上方槽位1图标')
                t_sh=validate_icon_word(top_sh_var.get(),'上方槽位2图标')
                b_in=validate_icon_word(bot_in_var.get(),'下方槽位1图标')
                b_sh=validate_icon_word(bot_sh_var.get(),'下方槽位2图标')
            except Exception as exc:
                messagebox.showerror('图标代号格式有误',str(exc),parent=dialog)
                return
            title_desc=f'同步更新为 {b_in} / {b_sh}' if sync_title_var.get() else '保持当前不变'
            if messagebox.askokcancel(
                '更新相机图标名称',
                f'即将更新相机创意外观图标名称：\n'
                f'· 上方带数字 1~6 快捷图标：3 {t_in} ／ 4 {t_sh}\n'
                f'· 下方无数字基础图标：{b_in} ／ {b_sh}\n'
                f'· 屏幕中央橙色大字标题：{title_desc}\n\n'
                f'将自动核对相机、执行 30 项指令级离线仿真并保存完整备份。\n操作期间请保持供电和 USB 连接，是否开始？',
                parent=dialog,
            ):
                dialog.destroy()
                cmd=[
                    'install-icons','--power-confirmed',
                    '--top-in',t_in,'--top-sh',t_sh,
                    '--bot-in',b_in,'--bot-sh',b_sh,
                ]
                if sync_title_var.get():
                    cmd.extend(['--title-in',b_in,'--title-sh',b_sh])
                self.start(cmd)

        ttk.Button(icon_actions,text='检查相机图标',command=check_icons).pack(side='left',padx=(0,8))
        ttk.Button(icon_actions,text='更新相机图标',command=update_icons).pack(side='right')
        dialog.update_idletasks()
        x=self.root.winfo_rootx()+(self.root.winfo_width()-dialog.winfo_reqwidth())//2
        y=self.root.winfo_rooty()+(self.root.winfo_height()-dialog.winfo_reqheight())//2
        dialog.geometry(f'+{max(x,0)}+{max(y,0)}')
        dialog.grab_set()
        dialog.focus_set()

    def start(self,args):
        if self.busy:return
        self.busy=True;self.error=None;self.result.set('正在处理…');self.refresh()
        self.progress.configure(mode='indeterminate')
        self.progress.start(12)
        def job():
            try:
                if args[0]=='filters':
                    output=Path(args[2])
                    in_cube=args[3] or None
                    sh_cube=args[4] or None
                    looks=tuple(args[5:])
                    apply_profiles(Path(args[1]),output,looks,in_cube_path=in_cube,sh_cube_path=sh_cube)
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
                    elif value.startswith(('外观文件已生成：','FL2／FL3 已导入','FL2／FL3（含所选 LUT 直出）已导入','相机已安装')):
                        self.result.set(value)
                    elif value.startswith(('图标资源：','相机图标资源已更新','相机图标已是所选名称','图标更新和回读通过','正在更新并回读图标','正在准备图标资源')):
                        self.result.set(value)
                    elif value.startswith('写入并回读成功'):
                        self.result.set('写入成功。拔线关机，等指示灯熄灭后取电池一分钟，再开机试听。')
            else:
                self.busy=False;self.progress.stop();self.progress.configure(mode='determinate',value=0);self.refresh()
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

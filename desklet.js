// SysWatch Desklet v2.2 — i18n + extended GPU support

const Desklet  = imports.ui.desklet;
const St       = imports.gi.St;
const GLib     = imports.gi.GLib;
const Gio      = imports.gi.Gio;
const Mainloop = imports.mainloop;
const Settings = imports.ui.settings;
const Gettext  = imports.gettext;

const UUID = 'syswatch@marian';

// ─── i18n ─────────────────────────────────────────────────────────────────────
Gettext.bindtextdomain(UUID, GLib.get_home_dir() + '/.local/share/locale');
function _(str) { return Gettext.dgettext(UUID, str); }

// ─── I/O helpers ──────────────────────────────────────────────────────────────

function readSync(path) {
    try {
        let f = Gio.File.new_for_path(path);
        let [ok, bytes] = f.load_contents(null);
        if (!ok) return null;
        return bytes instanceof Uint8Array ? new TextDecoder().decode(bytes) : bytes.toString();
    } catch(e) { return null; }
}

function spawnAsync(argv, callback) {
    try {
        let proc = Gio.Subprocess.new(
            argv,
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE
        );
        proc.communicate_utf8_async(null, null, function(p, res) {
            try {
                let [, out] = p.communicate_utf8_finish(res);
                callback(null, (out || '').trim());
            } catch(e) { callback(e, ''); }
        });
    } catch(e) { callback(e, ''); }
}

// ─── Desklet ──────────────────────────────────────────────────────────────────

function SysWatchDesklet(metadata, desklet_id) {
    this._init(metadata, desklet_id);
}

SysWatchDesklet.prototype = {
    __proto__: Desklet.Desklet.prototype,

    _init: function(metadata, desklet_id) {
        Desklet.Desklet.prototype._init.call(this, metadata, desklet_id);

        this._cpuPrev     = null;
        this._cpuCorePrev = [];
        this._netRows     = {};
        this._coreRows    = [];
        this._timers      = [];
        this._destroyed   = false;

        this.settings = new Settings.DeskletSettings(this, UUID, desklet_id);
        this._bindSettings();
        this._buildUI();
        this._startTimers();
    },

    // ── Settings ──────────────────────────────────────────────────────────────

    _bindSettings: function() {
        let IN = Settings.BindingDirection.IN;
        let restart = () => this._restartTimers();

        this.settings.bindProperty(IN, 'refresh-system',        'refreshSystem',   restart, null);
        this.settings.bindProperty(IN, 'refresh-governor',      'refreshGovernor', restart, null);
        this.settings.bindProperty(IN, 'refresh-gpu',           'refreshGpu',      restart, null);
        this.settings.bindProperty(IN, 'refresh-docker',        'refreshDocker',   restart, null);
        this.settings.bindProperty(IN, 'refresh-network',       'refreshNetwork',  restart, null);
        this.settings.bindProperty(IN, 'show-cpu-temp',    'showCpuTemp',    () => this._toggleCpuTemp(), null);
        this.settings.bindProperty(IN, 'show-per-core',    'showPerCore',    () => this._togglePerCore(), null);
        this.settings.bindProperty(IN, 'show-gpu',         'showGpu',        () => this._toggleGpu(),     null);
        this.settings.bindProperty(IN, 'temp-fahrenheit',  'tempFahrenheit', null, null);
        this.settings.bindProperty(IN, 'docker-enabled',   'dockerEnabled',  () => this._toggleDocker(),  null);
        this.settings.bindProperty(IN, 'docker-max-containers', 'dockerMax', null, null);
        this.settings.bindProperty(IN, 'network-hosts',    'networkHosts',   () => this._rebuildNetworkRows(), null);
        this.settings.bindProperty(IN, 'bar-width',        'barWidth',       null, null);
    },

    // ── UI ────────────────────────────────────────────────────────────────────

    _buildUI: function() {
        this._main = new St.BoxLayout({ vertical: true, style_class: 'syswatch-main' });
        this.setContent(this._main);

        this._main.add_actor(new St.Label({ text: '⚙  SysWatch', style_class: 'syswatch-header' }));
        this._main.add_actor(new St.Widget({ style_class: 'syswatch-hsep' }));

        this._buildSystemSection();
        this._buildGovernorSection();
        this._buildGpuSection();
        this._buildDockerSection();
        this._buildNetworkSection();
    },

    _sectionTitle: function(text) {
        return new St.Label({ text: text, style_class: 'syswatch-section-title' });
    },

    // ── CPU / RAM ─────────────────────────────────────────────────────────────

    _buildSystemSection: function() {
        this._sysSection = new St.BoxLayout({ vertical: true, style_class: 'syswatch-section' });
        this._sysSection.add_actor(this._sectionTitle(_('CPU / RAM')));

        let cpuRow      = this._makeBarRow(_('CPU'));
        this._cpuFill   = cpuRow.fill;
        this._cpuPctLbl = cpuRow.pct;
        this._cpuTempLbl = new St.Label({ text: '', style_class: 'syswatch-temp' });
        cpuRow.box.add_actor(this._cpuTempLbl);
        this._sysSection.add_actor(cpuRow.box);

        let ramRow      = this._makeBarRow('RAM');
        this._ramFill   = ramRow.fill;
        this._ramPctLbl = ramRow.pct;
        this._sysSection.add_actor(ramRow.box);

        this._buildCoreSubsection();
        this._main.add_actor(this._sysSection);

        if (!this.showCpuTemp) this._cpuTempLbl.hide();
    },

    _buildCoreSubsection: function() {
        let stat = readSync('/proc/stat');
        let coreCount = 0;
        if (stat) stat.split('\n').forEach(l => { if (/^cpu\d/.test(l)) coreCount++; });

        this._coreRows = [];
        this._coreSub  = new St.BoxLayout({ vertical: true, style_class: 'syswatch-core-sub' });

        let cols = new St.BoxLayout({ style_class: 'syswatch-core-cols' });
        let col1 = new St.BoxLayout({ vertical: true, style_class: 'syswatch-core-col' });
        let col2 = new St.BoxLayout({ vertical: true, style_class: 'syswatch-core-col' });
        let half = Math.ceil(coreCount / 2);

        for (let i = 0; i < coreCount; i++) {
            let row = this._makeMiniBarRow('c' + i);
            this._coreRows.push(row);
            (i < half ? col1 : col2).add_actor(row.box);
        }
        cols.add_actor(col1);
        if (coreCount > 1) cols.add_actor(col2);
        this._coreSub.add_actor(cols);
        this._sysSection.add_actor(this._coreSub);
        if (!this.showPerCore) this._coreSub.hide();
    },

    _toggleCpuTemp: function() {
        if (!this._cpuTempLbl) return;
        this.showCpuTemp ? this._cpuTempLbl.show() : this._cpuTempLbl.hide();
    },
    _togglePerCore: function() {
        if (!this._coreSub) return;
        this.showPerCore ? this._coreSub.show() : this._coreSub.hide();
    },

    // ── Bar helpers ───────────────────────────────────────────────────────────

    _makeBarRow: function(label) {
        let box = new St.BoxLayout({ style_class: 'syswatch-bar-row' });
        let W   = this.barWidth || 160;
        box.add_actor(new St.Label({ text: label, style_class: 'syswatch-bar-label' }));
        let bg   = new St.Widget({ style_class: 'syswatch-bar-bg',   width: W, height: 14 });
        let fill = new St.Widget({ style_class: 'syswatch-bar-fill', width: 0, height: 14 });
        bg.add_actor(fill);
        box.add_actor(bg);
        let pct = new St.Label({ text: '–', style_class: 'syswatch-bar-pct' });
        box.add_actor(pct);
        return { box, fill, pct };
    },

    _makeMiniBarRow: function(label) {
        let W   = 65;
        let box = new St.BoxLayout({ style_class: 'syswatch-mini-row' });
        box.add_actor(new St.Label({ text: label, style_class: 'syswatch-mini-label' }));
        let bg   = new St.Widget({ style_class: 'syswatch-bar-bg',   width: W, height: 10 });
        let fill = new St.Widget({ style_class: 'syswatch-bar-fill', width: 0, height: 10 });
        bg.add_actor(fill);
        box.add_actor(bg);
        let pct = new St.Label({ text: '–', style_class: 'syswatch-mini-pct' });
        box.add_actor(pct);
        return { box, fill, pct, W };
    },

    _setBar: function(fill, pctLbl, pct, customText, barW) {
        if (!fill || !pctLbl) return;
        if (isNaN(pct) || pct === null) pct = 0;
        let W  = barW || this.barWidth || 160;
        let clamped = Math.min(100, Math.max(0, pct));
        fill.width = Math.round(clamped / 100 * W);
        pctLbl.set_text(customText || pct.toFixed(1) + '%');
        fill.style_class = clamped >= 90 ? 'syswatch-bar-fill syswatch-danger'
                         : clamped >= 70 ? 'syswatch-bar-fill syswatch-warning'
                         :                 'syswatch-bar-fill';
    },

    // ── System update ─────────────────────────────────────────────────────────

    _updateSystem: function() {
        if (this._destroyed) return;
        try { this._doUpdateSystem(); } catch(e) { global.logError('[SysWatch] system: ' + e); }
    },

    _doUpdateSystem: function() {
        let stat = readSync('/proc/stat');
        if (stat) {
            let lines = stat.split('\n');

            // Total CPU
            let parts = lines[0].split(/\s+/).slice(1).map(Number);
            let total = parts.reduce((a, b) => a + b, 0);
            let idle  = parts[3] + (parts[4] || 0);
            if (this._cpuPrev) {
                let dt  = total - this._cpuPrev.total;
                let di  = idle  - this._cpuPrev.idle;
                this._setBar(this._cpuFill, this._cpuPctLbl, dt > 0 ? Math.max(0, (1 - di/dt)*100) : 0);
            }
            this._cpuPrev = { total, idle };

            // Per-core
            if (this.showPerCore && this._coreRows.length > 0) {
                let ci = 0;
                for (let i = 1; i < lines.length && ci < this._coreRows.length; i++) {
                    if (!/^cpu\d/.test(lines[i])) break;
                    let cp = lines[i].split(/\s+/).slice(1).map(Number);
                    let ct = cp.reduce((a,b) => a+b, 0);
                    let ci2 = cp[3] + (cp[4] || 0);
                    let prev = this._cpuCorePrev[ci];
                    if (prev) {
                        let dt  = ct - prev.total, di = ci2 - prev.idle;
                        let pct = dt > 0 ? Math.max(0, (1 - di/dt)*100) : 0;
                        let row = this._coreRows[ci];
                        this._setBar(row.fill, row.pct, pct, pct.toFixed(0)+'%', row.W);
                    }
                    this._cpuCorePrev[ci] = { total: ct, idle: ci2 };
                    ci++;
                }
            }
        }

        // CPU temperature (coretemp Package id 0 preferred; acpitz last-resort)
        if (this.showCpuTemp && this._cpuTempLbl) {
            let temp = this._readHwmonTempLabel('coretemp', 'Package id 0');
            if (temp === null) temp = this._readHwmonTemp(['coretemp', 'k10temp', 'zenpower', 'acpitz']);
            let s = this._formatTemp(temp);
            this._cpuTempLbl.set_text(s !== null ? `  🌡 ${s}` : '');
        }

        // RAM
        let mem = readSync('/proc/meminfo');
        if (mem) {
            let g = k => { let m = mem.match(new RegExp(k+':\\s+(\\d+)')); return m ? +m[1] : 0; };
            let tot = g('MemTotal'), avail = g('MemAvailable');
            let used = tot - avail, pct = tot > 0 ? (used/tot)*100 : 0;
            this._setBar(this._ramFill, this._ramPctLbl, pct,
                `${(used/1048576).toFixed(1)} / ${(tot/1048576).toFixed(1)} G`);
        }
    },

    // ── CPU Governor ──────────────────────────────────────────────────────────

    _buildGovernorSection: function() {
        this._govSection = new St.BoxLayout({ vertical: true, style_class: 'syswatch-section' });
        this._govSection.add_actor(this._sectionTitle(_('CPU GOVERNOR')));
        this._govLabel  = new St.Label({ text: '–', style_class: 'syswatch-mono' });
        this._freqLabel = new St.Label({ text: '',  style_class: 'syswatch-dim'  });
        this._govSection.add_actor(this._govLabel);
        this._govSection.add_actor(this._freqLabel);
        this._main.add_actor(this._govSection);
    },

    _updateGovernor: function() {
        if (this._destroyed) return;
        try { this._doUpdateGovernor(); } catch(e) { global.logError('[SysWatch] governor: ' + e); }
    },

    _doUpdateGovernor: function() {
        let govMap = {}, freqMap = {};
        for (let i = 0; i < 64; i++) {
            let gov = readSync(`/sys/devices/system/cpu/cpu${i}/cpufreq/scaling_governor`);
            if (!gov) break;
            govMap[i] = gov.trim();
            let f = readSync(`/sys/devices/system/cpu/cpu${i}/cpufreq/scaling_cur_freq`);
            if (f) freqMap[i] = Math.round(+f / 1000);
        }
        let nums = Object.keys(govMap).map(Number);
        if (!nums.length) { this._govLabel.set_text(_('not available')); return; }

        let groups = {};
        nums.forEach(n => { let g = govMap[n]; (groups[g] = groups[g]||[]).push(n); });
        let lines = Object.keys(groups).map(gov => {
            let ns = groups[gov].sort((a,b)=>a-b);
            let r  = ns.length > 2 ? `cpu${ns[0]}–${ns[ns.length-1]}` : ns.map(n=>`cpu${n}`).join(',');
            return `${r}:  ${gov}`;
        });
        this._govLabel.set_text(lines.join('\n'));

        let freqs = Object.keys(freqMap).map(k => freqMap[k]);
        if (freqs.length) {
            let avg = Math.round(freqs.reduce((a,b)=>a+b,0)/freqs.length);
            let mn  = Math.min.apply(null, freqs), mx = Math.max.apply(null, freqs);
            this._freqLabel.set_text(mx-mn < 50 ? `⏱ ${avg} MHz` : `⏱ ${mn}–${mx} MHz  ∅${avg}`);
        }
    },

    // ── GPU ───────────────────────────────────────────────────────────────────

    _buildGpuSection: function() {
        this._gpuSection = new St.BoxLayout({ vertical: true, style_class: 'syswatch-section' });
        this._gpuSection.add_actor(this._sectionTitle(_('GPU')));

        let row          = this._makeBarRow(_('Load'));
        this._gpuFill    = row.fill;
        this._gpuPctLbl  = row.pct;
        this._gpuTempLbl = new St.Label({ text: '', style_class: 'syswatch-temp' });
        row.box.add_actor(this._gpuTempLbl);
        this._gpuSection.add_actor(row.box);

        this._gpuInfoLbl = new St.Label({ text: '–', style_class: 'syswatch-dim' });
        this._gpuSection.add_actor(this._gpuInfoLbl);
        this._main.add_actor(this._gpuSection);
        if (this.showGpu === false) this._gpuSection.hide();
    },

    _toggleGpu: function() {
        if (!this._gpuSection) return;
        this.showGpu === false ? this._gpuSection.hide() : this._gpuSection.show();
    },

    _updateGpu: function() {
        if (this._destroyed || this.showGpu === false) return;
        try { this._doUpdateGpu(); } catch(e) { global.logError('[SysWatch] gpu: ' + e); }
    },

    _doUpdateGpu: function() {
        // ── 1. NVIDIA ─────────────────────────────────────────────────────────
        spawnAsync(['nvidia-smi',
            '--query-gpu=utilization.gpu,temperature.gpu,name',
            '--format=csv,noheader,nounits'], (err, out) => {

            try {
                if (this._destroyed) return;
                if (!err && out) {
                    // nvidia-smi may return multiple lines for multi-GPU — use first
                    let line = out.trim().split('\n')[0];
                    let p    = line.split(',').map(s => s.trim());
                    if (p.length >= 2 && !isNaN(p[0])) {
                        let temp = !isNaN(p[1]) ? +p[1] : null;
                        let ts   = this._formatTemp(temp);
                        this._gpuSection.show();
                        this._setBar(this._gpuFill, this._gpuPctLbl, +p[0]);
                        this._gpuTempLbl.set_text(ts !== null ? `  🌡 ${ts}` : '');
                        this._gpuInfoLbl.set_text(p.slice(2).join(',').trim().slice(0, 32));
                        return;
                    }
                }

                // ── 2. AMD ────────────────────────────────────────────────────
                for (let card of ['/sys/class/drm/card0', '/sys/class/drm/card1',
                                   '/sys/class/drm/card2']) {
                    let util = readSync(card + '/device/gpu_busy_percent');
                    if (util !== null) {
                        let pct  = parseFloat(util);
                        if (isNaN(pct)) pct = 0;
                        let temp = this._readHwmonTemp(['amdgpu', 'radeon']);
                        let ts   = this._formatTemp(temp);
                        // Try to read actual GPU model name
                        let nameRaw = readSync(card + '/device/product_name')
                                   || readSync(card + '/device/label');
                        let name = nameRaw ? nameRaw.trim().slice(0, 32) : _('AMD GPU');
                        this._gpuSection.show();
                        this._setBar(this._gpuFill, this._gpuPctLbl, pct);
                        this._gpuTempLbl.set_text(ts !== null ? `  🌡 ${ts}` : '');
                        this._gpuInfoLbl.set_text(name);
                        return;
                    }
                }

                // ── 3. Intel i915 / Xe ────────────────────────────────────────
                for (let card of ['/sys/class/drm/card0', '/sys/class/drm/card1',
                                   '/sys/class/drm/card2']) {
                    let act = readSync(card + '/gt_act_freq_mhz');
                    let max = readSync(card + '/gt_max_freq_mhz');
                    if (act && max) {
                        let actMhz = parseFloat(act), maxMhz = parseFloat(max);
                        if (isNaN(actMhz) || isNaN(maxMhz) || maxMhz === 0) { actMhz = 0; maxMhz = 1; }
                        let pct    = Math.round(actMhz / maxMhz * 100);
                        let cur    = readSync(card + '/gt_cur_freq_mhz');
                        let curMhz = cur ? parseFloat(cur) : actMhz;
                        // Intel iGPU shares die — fall back to package temp
                        let temp = this._readHwmonTemp(['i915', 'xe']);
                        if (temp === null) temp = this._readHwmonTempLabel('coretemp', 'Package id 0');
                        if (temp === null) temp = this._readThermalZone('x86_pkg_temp');
                        let ts = this._formatTemp(temp);
                        this._gpuSection.show();
                        this._setBar(this._gpuFill, this._gpuPctLbl, pct,
                                     `${Math.round(curMhz)} / ${Math.round(maxMhz)} MHz`);
                        this._gpuTempLbl.set_text(ts !== null ? `  🌡 ${ts}` : '');
                        this._gpuInfoLbl.set_text(_('Intel iGPU'));
                        return;
                    }
                }

                // ── 4. Qualcomm Adreno (kgsl) ─────────────────────────────────
                let adreno = readSync('/sys/class/kgsl/kgsl-3d0/gpu_busy_percentage');
                if (adreno !== null) {
                    let pct     = parseFloat(adreno) || 0;
                    let fRaw    = readSync('/sys/class/kgsl/kgsl-3d0/devfreq/cur_freq');
                    let freqStr = fRaw ? `${Math.round(+fRaw/1e6)} MHz` : '';
                    let temp    = this._readThermalGpu();
                    let ts      = this._formatTemp(temp);
                    this._gpuSection.show();
                    this._setBar(this._gpuFill, this._gpuPctLbl, pct);
                    this._gpuTempLbl.set_text(ts !== null ? `  🌡 ${ts}` : '');
                    this._gpuInfoLbl.set_text(`${_('Qualcomm Adreno')}  ${freqStr}`);
                    return;
                }

                // ── 5. ARM Mali ────────────────────────────────────────────────
                for (let path of [
                    '/sys/class/misc/mali0/device/utilization',
                    '/sys/kernel/debug/mali/gpu_utilization',
                    '/sys/devices/platform/mali/utilization_pp'
                ]) {
                    let util = readSync(path);
                    if (util !== null) {
                        let pct  = parseFloat(util) || 0;
                        let temp = this._readHwmonTemp(['mali']);
                        let ts   = this._formatTemp(temp);
                        this._gpuSection.show();
                        this._setBar(this._gpuFill, this._gpuPctLbl, pct);
                        this._gpuTempLbl.set_text(ts !== null ? `  🌡 ${ts}` : '');
                        this._gpuInfoLbl.set_text(_('ARM Mali'));
                        return;
                    }
                }

                // ── 6. Raspberry Pi VideoCore ──────────────────────────────────
                spawnAsync(['vcgencmd', 'measure_temp'], (verr, vout) => {
                    if (this._destroyed) return;
                    try {
                        if (!verr && vout && vout.indexOf('temp=') >= 0) {
                            let m    = vout.match(/temp=([\d.]+)/);
                            let temp = m ? parseFloat(m[1]) : null;
                            let ts   = this._formatTemp(temp);
                            this._gpuSection.show();
                            this._setBar(this._gpuFill, this._gpuPctLbl, 0, _('VideoCore GPU'));
                            this._gpuTempLbl.set_text(ts !== null ? `  🌡 ${ts}` : '');
                            this._gpuInfoLbl.set_text('');
                        } else {
                            this._gpuSection.hide();
                        }
                    } catch(e) { global.logError('[SysWatch] vcgencmd: ' + e); }
                });
            } catch(e) { global.logError('[SysWatch] gpu callback: ' + e); }
        });
    },

    // ── Temperature helpers ───────────────────────────────────────────────────

    _formatTemp: function(celsius) {
        if (celsius === null) return null;
        if (this.tempFahrenheit)
            return (celsius * 9 / 5 + 32).toFixed(0) + '°F';
        return celsius + '°C';
    },

    _readHwmonTemp: function(names) {
        // Build index first, then iterate by name priority
        let hwmonMap = {};
        for (let i = 0; i < 16; i++) {
            let n = readSync(`/sys/class/hwmon/hwmon${i}/name`);
            if (!n) break;
            hwmonMap[n.trim()] = i;
        }
        for (let name of names) {
            if (!(name in hwmonMap)) continue;
            let v = readSync(`/sys/class/hwmon/hwmon${hwmonMap[name]}/temp1_input`);
            if (v) {
                let t = Math.round(+v / 1000);
                if (t > -50 && t < 200) return t;
            }
        }
        return null;
    },

    _readHwmonTempLabel: function(sensorName, labelStr) {
        for (let i = 0; i < 16; i++) {
            let n = readSync(`/sys/class/hwmon/hwmon${i}/name`);
            if (!n) break;
            if (n.trim() !== sensorName) continue;
            for (let j = 1; j <= 16; j++) {
                let lbl = readSync(`/sys/class/hwmon/hwmon${i}/temp${j}_label`);
                if (!lbl) break;
                if (lbl.trim() === labelStr) {
                    let v = readSync(`/sys/class/hwmon/hwmon${i}/temp${j}_input`);
                    if (v) {
                        let t = Math.round(+v / 1000);
                        if (t > -50 && t < 200) return t;
                    }
                }
            }
        }
        return null;
    },

    _readThermalZone: function(typeName) {
        for (let i = 0; i < 20; i++) {
            let type = readSync(`/sys/class/thermal/thermal_zone${i}/type`);
            if (!type) break;
            if (type.trim() === typeName) {
                let v = readSync(`/sys/class/thermal/thermal_zone${i}/temp`);
                if (v) {
                    let t = Math.round(+v / 1000);
                    if (t > -50 && t < 200) return t;
                }
            }
        }
        return null;
    },

    _readThermalGpu: function() {
        let gpuKeywords = ['gpu', 'GPU_therm', 'gpu-thermal'];
        for (let i = 0; i < 20; i++) {
            let type = readSync(`/sys/class/thermal/thermal_zone${i}/type`);
            if (!type) break;
            let t = type.trim().toLowerCase();
            for (let kw of gpuKeywords) {
                if (t.indexOf(kw.toLowerCase()) >= 0) {
                    let v = readSync(`/sys/class/thermal/thermal_zone${i}/temp`);
                    if (v) { let c = Math.round(+v/1000); if (c > -50 && c < 200) return c; }
                }
            }
        }
        return null;
    },

    // ── Docker ────────────────────────────────────────────────────────────────

    _buildDockerSection: function() {
        this._dockerSection = new St.BoxLayout({ vertical: true, style_class: 'syswatch-section' });
        this._dockerSection.add_actor(this._sectionTitle(_('DOCKER')));
        this._dockerList = new St.BoxLayout({ vertical: true });
        this._dockerSection.add_actor(this._dockerList);
        this._main.add_actor(this._dockerSection);
        if (this.dockerEnabled === false) this._dockerSection.hide();
    },

    _toggleDocker: function() {
        this.dockerEnabled === false ? this._dockerSection.hide() : this._dockerSection.show();
    },

    _updateDocker: function() {
        if (this._destroyed || this.dockerEnabled === false) return;
        spawnAsync(['docker', 'ps', '-a', '--format', '{{json .}}'], (err, out) => {
            if (this._destroyed || !this._dockerList) return;
            try {
                this._dockerList.get_children().forEach(c => c.destroy());
                if (err) {
                    this._dockerList.add_actor(new St.Label({
                        text: '⚠  ' + (err.message||'docker error').slice(0, 50),
                        style_class: 'syswatch-err' }));
                    return;
                }
                let containers = [];
                out.split('\n').forEach(line => {
                    line = line.trim();
                    if (line) try { containers.push(JSON.parse(line)); } catch(e) {}
                });
                containers.sort((a,b) => {
                    let ar = (a.State||'').indexOf('running') >= 0 ? 0 : 1;
                    let br = (b.State||'').indexOf('running') >= 0 ? 0 : 1;
                    return ar - br || (a.Names||'').localeCompare(b.Names||'');
                });
                let max = this.dockerMax || 30;
                if (!containers.length) {
                    this._dockerList.add_actor(new St.Label({
                        text: '  ' + _('no containers'), style_class: 'syswatch-dim' }));
                }
                containers.slice(0, max).forEach(c => {
                    this._dockerList.add_actor(this._makeDockerRow(c));
                });
                if (containers.length > max) {
                    this._dockerList.add_actor(new St.Label({
                        text: `  … ${containers.length - max} ` + _('more'),
                        style_class: 'syswatch-dim' }));
                }
            } catch(e) { global.logError('[SysWatch] docker callback: ' + e); }
        });
    },

    _makeDockerRow: function(c) {
        let box     = new St.BoxLayout({ style_class: 'syswatch-row' });
        let state   = (c.State||c.Status||'').toLowerCase();
        let running = state.indexOf('running') >= 0;
        box.add_actor(new St.Label({
            text: running ? '● ' : '○ ',
            style_class: running ? 'syswatch-ok' : 'syswatch-err' }));
        let name = (c.Names||'unknown').replace(/^\//, '').split(',')[0];
        box.add_actor(new St.Label({ text: name.slice(0,24),
            style_class: 'syswatch-mono syswatch-col-name' }));
        box.add_actor(new St.Label({ text: (c.Status||state).slice(0,22),
            style_class: 'syswatch-dim' }));
        return box;
    },

    // ── Network ───────────────────────────────────────────────────────────────

    _buildNetworkSection: function() {
        this._netSection = new St.BoxLayout({ vertical: true, style_class: 'syswatch-section' });
        this._netSection.add_actor(this._sectionTitle(_('NETWORK')));
        this._netList = new St.BoxLayout({ vertical: true });
        this._netSection.add_actor(this._netList);
        this._main.add_actor(this._netSection);
        this._rebuildNetworkRows();
    },

    _rebuildNetworkRows: function() {
        if (!this._netList) return;
        this._netList.get_children().forEach(c => c.destroy());
        this._netRows = {};
        (this.networkHosts || []).forEach(h => {
            if (!h.host) return;
            let row = this._makeNetRow(h.name||h.host, h.host);
            this._netList.add_actor(row.box);
            this._netRows[h.host] = row;
        });
    },

    _makeNetRow: function(name, host) {
        let box  = new St.BoxLayout({ style_class: 'syswatch-row' });
        let icon = new St.Label({ text: '○ ', style_class: 'syswatch-unknown' });
        box.add_actor(icon);
        box.add_actor(new St.Label({ text: name.slice(0,10),
            style_class: 'syswatch-mono syswatch-col-name' }));
        box.add_actor(new St.Label({ text: host,
            style_class: 'syswatch-dim syswatch-col-host' }));
        let lat = new St.Label({ text: '–', style_class: 'syswatch-lat' });
        box.add_actor(lat);
        return { box, icon, lat };
    },

    _updateNetwork: function() {
        if (this._destroyed) return;
        (this.networkHosts||[]).forEach(h => { if (h.host) this._pingHost(h.host); });
    },

    _pingHost: function(host) {
        spawnAsync(['ping', '-c', '1', '-W', '1', host], (err, out) => {
            if (this._destroyed) return;
            try {
                let row = this._netRows[host];
                if (!row) return;
                if (!err && out && out.indexOf('100%') < 0) {
                    let m  = out.match(/time[=<]([\d.]+)\s*ms/);
                    let ms = m ? +m[1] : 0;
                    row.icon.set_text('● ');
                    row.icon.style_class = 'syswatch-ok';
                    row.lat.set_text(ms > 0.5 ? ms.toFixed(1)+' ms' : '< 1 ms');
                } else {
                    row.icon.set_text('○ ');
                    row.icon.style_class = 'syswatch-err';
                    row.lat.set_text('OFFLINE');
                }
            } catch(e) { global.logError('[SysWatch] ping callback: ' + e); }
        });
    },

    // ── Timers ────────────────────────────────────────────────────────────────

    _startTimers: function() {
        this._updateSystem();
        this._updateGovernor();
        this._updateGpu();
        this._updateDocker();
        this._updateNetwork();

        this._timers = [
            Mainloop.timeout_add_seconds(Math.max(1,  this.refreshSystem  ||2),  ()=>{ this._updateSystem();   return true; }),
            Mainloop.timeout_add_seconds(Math.max(5,  this.refreshGovernor||10), ()=>{ this._updateGovernor(); return true; }),
            Mainloop.timeout_add_seconds(Math.max(1,  this.refreshGpu     ||3),  ()=>{ this._updateGpu();      return true; }),
            Mainloop.timeout_add_seconds(Math.max(5,  this.refreshDocker  ||10), ()=>{ this._updateDocker();   return true; }),
            Mainloop.timeout_add_seconds(Math.max(10, this.refreshNetwork ||30), ()=>{ this._updateNetwork();  return true; })
        ];
    },

    _clearTimers:   function() { this._timers.forEach(t=>Mainloop.source_remove(t)); this._timers=[]; },
    _restartTimers: function() { this._clearTimers(); this._startTimers(); },
    on_desklet_removed: function() { this._destroyed = true; this._clearTimers(); }
};

function main(metadata, desklet_id) {
    return new SysWatchDesklet(metadata, desklet_id);
}

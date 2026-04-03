export const EOL = '\n';

export function hostname() { return __os_hostname(); }
export function homedir() { return __os_homedir(); }
export function tmpdir() { return __os_tmpdir(); }
export function platform() { return __os_platform(); }
export function arch() { return __os_arch(); }
export function type_() { return __os_type(); }
export function release() { return __os_release(); }
export function totalmem() { return __os_totalmem(); }
export function freemem() { return __os_freemem(); }
export function uptime() { return __os_uptime(); }
export function endianness() { return __os_endianness(); }

export function cpus() {
    const count = __os_cpus();
    return Array.from({ length: count }, () => ({
        model: '',
        speed: 0,
        times: { user: 0, nice: 0, sys: 0, idle: 0, irq: 0 },
    }));
}

export function networkInterfaces() { return {}; }
export function userInfo() {
    return {
        uid: -1, gid: -1,
        username: '',
        homedir: homedir(),
        shell: '',
    };
}

// Node.js uses `type` as the export name but it's a reserved word
// The module re-exports it correctly via default
export default {
    EOL, hostname, homedir, tmpdir, platform, arch,
    type: type_, release, cpus, totalmem, freemem, uptime,
    endianness, networkInterfaces, userInfo,
};

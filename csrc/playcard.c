/*
 * playcard - run a Yamaha Playcard on an emulated CX5M, and capture the FM.
 *
 *     playcard card.bin [-o out.fmlog] [--seconds N] [--roms DIR] [--quiet]
 *     playcard side-a.bin side-b.bin -o out.fmlog
 *
 * It plays until the CARD ENDS rather than for a fixed time: --seconds is a
 * ceiling.  See the loop after F2 for why the test is key-ons and not writes.
 *
 * The C twin of ../msx_player.py, and the reason it exists is speed: the Python
 * one runs at about 79% of real time, which is fine for asking questions and
 * hopeless for rendering audio.  Everything it knows was learned there first,
 * and the Python version stays the debugger - it can stop the machine and read
 * a byte, which is what actually cracks a bug.
 *
 * WHAT IS EMULATED
 *
 * Only what the cartridge touches:
 *
 *   - the Z80, from superzazu's core (MIT, see Z80_LICENSE)
 *   - the primary slot register on port 0xA8, and four 16K pages
 *   - the keyboard matrix on ports 0xAA/0xA9
 *   - the VDP's two ports, with its 16K of video memory and its registers,
 *     which is what --screen reads the cartridge's panel out of; no pixels
 *     are rendered, and the vblank flag is what the cartridge's interrupt
 *     gate at 0x7DD1 reads back
 *   - the PSG's ports, discarded
 *   - the SFG-01's YM2151 at 0x3FF0/0x3FF1, recorded rather than synthesised,
 *     with the chip's status readable from the DATA port where the SFG's own
 *     code polls it
 *
 * and the CR-01 card reader, which is not emulated: the two ROM routines that
 * take a bit from it are answered directly from the card image.
 *
 * WHAT A CAPTURE FROM THIS IS EVIDENCE OF
 *
 * One machine: the UPA-01 cartridge's rendering on an SFG-01's YM2151.  Not
 * "how a Playcard sounds", and not what a PC-100 or a PCS-30 would play from
 * the same bytes - the accompaniment patterns live in the instrument, and this
 * cartridge is a 1985 port with known bugs (dropped chord notes, a fixed feel
 * per fill rather than the rhythm's, silence on a same-root chart entry).
 * What it settles is what the CARD asked for, because Yamaha's own code does
 * the reading and nothing here understands the format.
 *
 * THREE THINGS THAT HAVE TO BE RIGHT
 *
 *   - the SFG answers across its WHOLE slot, the same 16K four times, so the
 *     signature "MCHFM0" is readable at 0x0080 while the ROM is at 0x4000;
 *   - the YM2151's status is read from 0x3FF1, the data port, not 0x3FF0;
 *   - LD A,I must set P/V from IFF2, or the ROM's save-and-restore idiom
 *     leaves interrupts off for ever and the music stops after one note.
 *
 * The first two are this file's business.  The third is the CPU core's, and
 * the reason for using a core that passes ZEXALL rather than writing one.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "z80.h"

#define CLOCK       3579545.0       /* the Z80's and the YM2151's clock */
#define OPM_BASE    0x3FF0

#define SLOT_BIOS   0
#define SLOT_CART   1
#define SLOT_SFG    2
#define SLOT_RAM    3

#define CR01_POLL     0x6892
#define CR01_POLL_RET 0x6895
#define CR01_BIT      0x68B2
#define CR01_BIT_RET  0x68B5

static const char *ROM_BIOS = "cx5m_basic-bios1.rom";
static const char *ROM_SFG  = "SFG01.ROM";
static const char *ROM_CART = "Play Card System (UPA-01) (1985) (Yamaha) (J).rom";

typedef struct {
    unsigned long cyc;
    uint8_t reg, val;
} fmwrite;

/* A read or a write of an address somebody asked to watch.  `pc` is the CPU's
 * program counter as the access happens, which is what says WHO touched it. */
#define MAXWATCH 8
#define MAXCARDS 4                 /* a two-sided card is two swipes */
typedef struct {
    unsigned long cyc;
    uint16_t addr, pc;
    uint8_t val, write;
} memtouch;

typedef struct {
    z80 cpu;
    uint8_t mem[0x10000];          /* what the CPU sees */
    uint8_t ram[0x10000];          /* RAM, kept while paged out */
    uint8_t *rom[4];               /* one 64K image a slot, NULL if empty */
    int page[4], writable[4];

    uint8_t keys[16];
    int krow;
    int vdp_flag;

    /* The VDP, far enough to read the screen back.  The cartridge does not use
     * the BIOS text routines at all - not one CALL to CHPUT, WRTVRM or LDIRVM
     * anywhere in its 16K - so there is nothing to intercept.  What it has is
     * one table-driven port writer at 0x7DB6: a byte count, then that many
     * bytes to port 0x99 or, with bit 7 set, to port 0x98.  So the only way to
     * see the panel is to keep the VRAM, which is all this does.  Nothing is
     * rendered; the screen comes back as the name table, which in SCREEN 0/1
     * holds character codes. */
    uint8_t vram[0x4000];
    uint8_t vreg[8];
    uint16_t vaddr;
    uint8_t vlatch;
    int vhalf;                     /* port 0x99 takes its argument in two */

    uint8_t opmreg;
    int opm_status, clka, clkb, t_load, t_irqen;

    char *bits;                    /* the cards, as '0'/'1', end to end */
    long nbits, bitpos;
    long swipe_end;                /* where the card now under the head ends */

    fmwrite *cap;
    long ncap, capmax;

    uint8_t psgreg;                /* the PSG, for machines with no FM at all */
    fmwrite *psg;
    long npsg, psgmax;

    uint16_t watch[MAXWATCH];      /* addresses to report every access to */
    int nwatch;
    memtouch *touch;
    long ntouch, touchmax;

    unsigned long *pchist;         /* one count an address, or NULL */
    unsigned long pcfrom;          /* not before this cycle */
    int pctick;
} msx;

/* Reads go through here on every fetch, so keep it a straight-line compare
 * against a list that is almost always empty. */
static void note_touch(msx *m, uint16_t a, uint8_t v, int write)
{
    int i;
    for (i = 0; i < m->nwatch; i++) {
        if (m->watch[i] != a)
            continue;
        if (m->ntouch == m->touchmax) {
            m->touchmax = m->touchmax ? m->touchmax * 2 : 1 << 12;
            m->touch = (memtouch *)realloc(m->touch, m->touchmax * sizeof *m->touch);
        }
        m->touch[m->ntouch].cyc = m->cpu.cyc;
        m->touch[m->ntouch].addr = a;
        m->touch[m->ntouch].pc = m->cpu.pc;
        m->touch[m->ntouch].val = v;
        m->touch[m->ntouch].write = (uint8_t)write;
        m->ntouch++;
        return;
    }
}

/* ------------------------------------------------------------------ memory */

static void publish_status(msx *m)
{
    /* The status comes back from the DATA port.  Putting it in the page the
     * CPU already reads keeps the read path a plain array access. */
    if (m->page[0] == SLOT_SFG)
        m->mem[OPM_BASE + 1] = (uint8_t)m->opm_status;
}

static void map_page(msx *m, int page, int slot, int force)
{
    int lo = page * 0x4000;
    if (!force && m->page[page] == slot)
        return;
    if (m->page[page] == SLOT_RAM)
        memcpy(m->ram + lo, m->mem + lo, 0x4000);
    if (slot == SLOT_RAM)
        memcpy(m->mem + lo, m->ram + lo, 0x4000);
    else if (m->rom[slot])
        memcpy(m->mem + lo, m->rom[slot] + lo, 0x4000);
    else
        memset(m->mem + lo, 0xFF, 0x4000);
    m->page[page] = slot;
    m->writable[page] = (slot == SLOT_RAM);
    if (page == 0 && slot == SLOT_SFG)
        publish_status(m);
}

static uint8_t rd(void *ud, uint16_t a)
{
    msx *m = (msx *)ud;
    if (m->nwatch)
        note_touch(m, a, m->mem[a], 0);
    return m->mem[a];
}

static void opm_write(msx *m, uint8_t reg, uint8_t val)
{
    switch (reg) {
    case 0x10: m->clka = (m->clka & 3) | (val << 2); break;
    case 0x11: m->clka = (m->clka & ~3) | (val & 3); break;
    case 0x12: m->clkb = val; break;
    case 0x14:
        m->t_load = val & 3;
        m->t_irqen = (val >> 2) & 3;
        if (val & 0x10) m->opm_status &= ~1;
        if (val & 0x20) m->opm_status &= ~2;
        publish_status(m);
        break;
    default: break;
    }
}

static void wr(void *ud, uint16_t a, uint8_t v)
{
    msx *m = (msx *)ud;
    int page = a >> 14;
    if (page == 0 && m->page[0] == SLOT_SFG && a >= OPM_BASE && a <= OPM_BASE + 7) {
        if (a == OPM_BASE) {
            m->opmreg = v;
        } else if (a == OPM_BASE + 1) {
            if (m->ncap == m->capmax) {
                m->capmax = m->capmax ? m->capmax * 2 : 1 << 16;
                m->cap = (fmwrite *)realloc(m->cap, m->capmax * sizeof *m->cap);
            }
            m->cap[m->ncap].cyc = m->cpu.cyc;
            m->cap[m->ncap].reg = m->opmreg;
            m->cap[m->ncap].val = v;
            m->ncap++;
            opm_write(m, m->opmreg, v);
        }
        return;
    }
    if (m->nwatch)
        note_touch(m, a, v, 1);
    if (m->writable[page])
        m->mem[a] = v;
}

/* ------------------------------------------------------------------- ports */

static uint8_t pin(z80 *z, uint8_t port)
{
    msx *m = (msx *)z->userdata;
    switch (port) {
    case 0xA8: return (uint8_t)(m->page[0] | (m->page[1] << 2)
                                | (m->page[2] << 4) | (m->page[3] << 6));
    case 0xA9: return m->keys[m->krow & 0x0F];
    case 0x98: {                    /* VRAM read, with autoincrement */
        uint8_t v = m->vram[m->vaddr & 0x3FFF];
        m->vaddr = (uint16_t)((m->vaddr + 1) & 0x3FFF);
        return v;
    }
    case 0x99: {                    /* VDP status; reading it clears vblank */
        uint8_t v = m->vdp_flag ? 0x80 : 0x00;
        m->vdp_flag = 0;
        m->vhalf = 0;               /* and resets the address latch, as on iron */
        return v;
    }
    default: return 0xFF;
    }
}

static void pout(z80 *z, uint8_t port, uint8_t value)
{
    msx *m = (msx *)z->userdata;
    if (port == 0xA8) {
        int p;
        for (p = 0; p < 4; p++)
            map_page(m, p, (value >> (p * 2)) & 3, 0);
    } else if (port == 0xAA) {
        m->krow = value & 0x0F;
    } else if (port == 0x98) {
        m->vram[m->vaddr & 0x3FFF] = value;
        m->vaddr = (uint16_t)((m->vaddr + 1) & 0x3FFF);
    } else if (port == 0x99) {
        /* Two bytes make one command.  The second says which: bit 7 set is a
         * register write, otherwise bits 13-8 of a VRAM address, with bit 6
         * choosing write setup over read setup.  Both set the address here. */
        if (!m->vhalf) {
            m->vlatch = value;
            m->vhalf = 1;
        } else {
            m->vhalf = 0;
            if (value & 0x80)
                m->vreg[value & 7] = m->vlatch;
            else
                m->vaddr = (uint16_t)(((value & 0x3F) << 8) | m->vlatch);
        }
    } else if (port == 0xA0) {
        m->psgreg = value & 0x0F;
    } else if (port == 0xA1) {
        /* The PSG is recorded the same way the YM2151 is.  On an MSX with no
         * FM module at all the cartridge plays here instead, which is the only
         * way to see that side of it. */
        if (m->npsg == m->psgmax) {
            m->psgmax = m->psgmax ? m->psgmax * 2 : 1 << 12;
            m->psg = (fmwrite *)realloc(m->psg, m->psgmax * sizeof *m->psg);
        }
        m->psg[m->npsg].cyc = m->cpu.cyc;
        m->psg[m->npsg].reg = m->psgreg;
        m->psg[m->npsg].val = value;
        m->npsg++;
    }
    /* the VDP and the rest are sinks */
}

/* ------------------------------------------------------------- the machine */

static uint8_t *load_rom(const char *dir, const char *name, long *len_out,
                         long want, const char *what)
{
    char path[1024];
    FILE *f;
    long n;
    uint8_t *buf;
    snprintf(path, sizeof path, "%s/%s", dir, name);
    f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr,
            "playcard: missing ROM image\n"
            "   %s\n"
            "   %ld bytes - %s\n"
            "These are Yamaha's and are not distributed with this program.\n"
            "Put them in %s, or pass --roms DIR.\n", path, want, what, dir);
        return NULL;
    }
    fseek(f, 0, SEEK_END); n = ftell(f); fseek(f, 0, SEEK_SET);
    buf = (uint8_t *)malloc(n);
    if (fread(buf, 1, n, f) != (size_t)n) { fclose(f); free(buf); return NULL; }
    fclose(f);
    if (n != want)
        fprintf(stderr, "playcard: warning: %s is %ld bytes, expected %ld\n",
                name, n, want);
    *len_out = n;
    return buf;
}

static int machine_init(msx *m, const char *romdir, int with_fm)
{
    long n;
    uint8_t *bios, *sfg, *cart;
    int i;

    memset(m, 0, sizeof *m);
    bios = load_rom(romdir, ROM_BIOS, &n, 32768,
                    "the CX5M's BIOS and BASIC, to boot the machine");
    if (!bios) return 0;
    m->rom[SLOT_BIOS] = (uint8_t *)calloc(1, 0x10000);
    memcpy(m->rom[SLOT_BIOS], bios, n > 0x8000 ? 0x8000 : n);
    free(bios);

    cart = load_rom(romdir, ROM_CART, &n, 16384, "the Play Card cartridge");
    if (!cart) return 0;
    m->rom[SLOT_CART] = (uint8_t *)calloc(1, 0x10000);
    memcpy(m->rom[SLOT_CART] + 0x4000, cart, n > 0x4000 ? 0x4000 : n);
    free(cart);

    if (!with_fm) {
        /* Leave the slot empty.  The UPA-01 was sold for MSX machines with no
         * FM hardware, and hunts for the signature "MCHFM0" to find out
         * whether any is fitted; with none it plays through the PSG instead. */
        m->rom[SLOT_SFG] = NULL;
        sfg = NULL;
    } else {
    sfg = load_rom(romdir, ROM_SFG, &n, 65536,
                   "the SFG-01 FM module, mirrored across its slot");
    if (!sfg) return 0;
    /* Mirrored four times: the signature has to be at 0x0080 in page 0 and the
     * YM2151 at 0x3FF0, while the ROM is read at 0x4000 in page 1. */
    m->rom[SLOT_SFG] = (uint8_t *)calloc(1, 0x10000);
    for (i = 0; i < 4; i++)
        memcpy(m->rom[SLOT_SFG] + i * 0x4000, sfg, 0x4000);
    free(sfg);
    }

    for (i = 0; i < 16; i++) m->keys[i] = 0xFF;
    m->page[0] = m->page[1] = SLOT_BIOS;
    m->page[2] = m->page[3] = SLOT_RAM;
    for (i = 0; i < 4; i++) map_page(m, i, m->page[i], 1);

    z80_init(&m->cpu);
    m->cpu.read_byte = rd;
    m->cpu.write_byte = wr;
    m->cpu.port_in = pin;
    m->cpu.port_out = pout;
    m->cpu.userdata = m;
    m->cpu.pc = 0x0000;
    m->cpu.sp = 0xF000;
    return 1;
}

static void feed(msx *m)
{
    if (m->page[1] != SLOT_CART)
        return;
    if (m->cpu.pc == CR01_POLL) {
        m->cpu.a = (m->bitpos < m->swipe_end) ? 0x80 : 0x00;
        m->cpu.pc = CR01_POLL_RET;
    } else if (m->cpu.pc == CR01_BIT) {
        if (m->bitpos >= m->swipe_end) {
            m->cpu.a = 0x00;
        } else {
            char b = m->bits[m->bitpos++];
            m->cpu.a = (uint8_t)(0xC0 | (b == '1' ? 0x20 : 0x00));
        }
        m->cpu.pc = CR01_BIT_RET;
    }
}

/* Timer A's period in Z80 cycles - the two chips share a clock. */
static unsigned long timer_a_period(const msx *m)
{
    if (m->clka >= 1024) return 0;
    return 64UL * (1024UL - (unsigned long)m->clka);
}

/*
 * Run for `seconds` of emulated time.
 *
 * Two things interrupt: the VDP at its frame rate, and the YM2151's timer A at
 * whatever the SFG programmed - about 109 Hz.  The timer matters even when
 * nothing services the interrupt, because the FM module's self-check waits to
 * see its own timer flag appear in the status byte; without it the module
 * reports the chip dead, the cartridge starts up paused, and a card reads
 * perfectly and then plays two notes and stops.
 */
/* The screen as text.  In SCREEN 0 and SCREEN 1 the name table holds one
 * character code a cell, and the BIOS font puts ASCII at its own codes, so the
 * table reads directly.  Anything outside printable ASCII is shown as a space:
 * this is for reading the cartridge's settings panel, not for pixel art. */
static int dump_screen(msx *m, const char *path, double at)
{
    FILE *f = fopen(path, "w");
    int row, col, cols, m1, m2, m3, odd = 0;
    unsigned base;
    if (!f)
        return 0;
    m1 = (m->vreg[1] >> 4) & 1;
    m2 = (m->vreg[1] >> 3) & 1;
    m3 = (m->vreg[0] >> 1) & 1;
    cols = m1 ? 40 : 32;
    base = (unsigned)m->vreg[2] * 0x400;
    fprintf(f, "# screen at %.2f s of emulated time\n", at);
    fprintf(f, "# mode bits M1=%d M2=%d M3=%d -> %d columns\n", m1, m2, m3, cols);
    fprintf(f, "# name table at 0x%04X\n", base);
    for (row = 0; row < 24; row++) {
        char line[64];
        int end = 0;
        for (col = 0; col < cols; col++) {
            uint8_t c = m->vram[(base + row * cols + col) & 0x3FFF];
            line[col] = (c >= 32 && c < 127) ? (char)c : ' ';
            if (line[col] != ' ')
                end = col + 1;
        }
        line[end] = 0;
        fprintf(f, "%2d| %s\n", row, line);
        for (col = 0; col < cols; col++) {
            uint8_t c = m->vram[(base + row * cols + col) & 0x3FFF];
            if (c && (c < 32 || c > 126))
                odd++;
        }
    }
    /* The panel's numeric fields are drawn with the cartridge's own glyphs,
     * which are not ASCII, so the text above shows them as blanks.  Where any
     * such cell exists the raw codes go out too, and nothing is lost. */
    if (odd) {
        fprintf(f, "# %d cells are not ASCII; the raw name table follows\n", odd);
        for (row = 0; row < 24; row++) {
            fprintf(f, "%2d>", row);
            for (col = 0; col < cols; col++)
                fprintf(f, " %02X", m->vram[(base + row * cols + col) & 0x3FFF]);
            fprintf(f, "\n");
        }
    }
    fclose(f);
    return 1;
}

static void run(msx *m, double seconds, double vdp_hz)
{
    unsigned long end = m->cpu.cyc + (unsigned long)(seconds * CLOCK);
    unsigned long vstep = (unsigned long)(CLOCK / vdp_hz);
    unsigned long vnext = m->cpu.cyc + vstep;
    unsigned long anext = 0, aper = 0;

    while (m->cpu.cyc < end) {
        feed(m);
        z80_step(&m->cpu);

        /* Where is it spending its time?  One count a PC, sampled sparsely,
         * is enough to find a wait loop and costs nothing when off. */
        if (m->pchist && m->cpu.cyc >= m->pcfrom && ++m->pctick >= 64) {
            m->pctick = 0;
            m->pchist[m->cpu.pc]++;
        }

        if (m->cpu.cyc >= vnext) {
            vnext += vstep;
            m->vdp_flag = 1;
            z80_gen_int(&m->cpu, 0xFF);
        }

        aper = timer_a_period(m);
        if (aper && (m->t_load & 1)) {
            if (!anext) anext = m->cpu.cyc + aper;
            if (m->cpu.cyc >= anext) {
                anext += aper;
                m->opm_status |= 1;
                publish_status(m);
                if (m->t_irqen & 1)
                    z80_gen_int(&m->cpu, 0xFF);
            }
        } else {
            anext = 0;
        }
    }
}

static void key(msx *m, int row, int mask, int down)
{
    if (down) m->keys[row] &= (uint8_t)~mask;
    else      m->keys[row] |= (uint8_t)mask;
}

#define F1_ROW 6
#define F1_BIT 0x20
#define F2_ROW 6
#define F2_BIT 0x40
#define F5_ROW 7                   /* F5 starts the card in free tempo */
#define F5_BIT 0x02

int main(int argc, char **argv)
{
    const char *out = NULL, *romdir = getenv("PLAYCARD_ROMS");
    double seconds = 400.0;        /* a ceiling, not a duration - see below */
    double vdp_hz = 50.0;
    double quiet_for = 4.0;        /* silence that means the card has ended */
    int quiet = 0, i, with_fm = 1, free_tempo = 0;
    double pcfrom = -1.0, ramat = 0.5;
    const char *ramout = NULL;
    const char *screenout = NULL;
    double screenat = -1.0;        /* < 0 means "when the card ends" */
    const char *psgout = NULL;
    const char *watchout = NULL;
    uint16_t watch[MAXWATCH];
    int nwatch = 0;
    const char *cards[MAXCARDS];
    int ncards = 0, ci;
    long csize[MAXCARDS], start[MAXCARDS], bitpos;
    msx *m;
    FILE *f;
    long k;
    uint8_t *data;

    if (!romdir) {
        /* Default to Roms/ beside the working directory, but look one level up
         * as well, so that building and running inside csrc/ finds the same
         * folder the rest of the repository uses.  Only when the caller named
         * neither --roms nor PLAYCARD_ROMS. */
        char probe[1024];
        FILE *pf;
        romdir = "Roms";
        snprintf(probe, sizeof probe, "%s/%s", romdir, ROM_BIOS);
        pf = fopen(probe, "rb");
        if (pf) {
            fclose(pf);
        } else {
            snprintf(probe, sizeof probe, "../%s/%s", "Roms", ROM_BIOS);
            pf = fopen(probe, "rb");
            if (pf) { fclose(pf); romdir = "../Roms"; }
        }
    }
    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-o") && i + 1 < argc) out = argv[++i];
        else if (!strcmp(argv[i], "--seconds") && i + 1 < argc) seconds = atof(argv[++i]);
        else if (!strcmp(argv[i], "--quiet-for") && i + 1 < argc) quiet_for = atof(argv[++i]);
        else if (!strcmp(argv[i], "--vdp-hz") && i + 1 < argc) vdp_hz = atof(argv[++i]);
        else if (!strcmp(argv[i], "--roms") && i + 1 < argc) romdir = argv[++i];
        else if (!strcmp(argv[i], "--quiet")) quiet = 1;
        else if (!strcmp(argv[i], "--no-fm")) with_fm = 0;
        else if (!strcmp(argv[i], "--f5")) free_tempo = 1;
        else if (!strcmp(argv[i], "--pc-from") && i + 1 < argc)
            pcfrom = atof(argv[++i]);
        else if (!strcmp(argv[i], "--ram-out") && i + 1 < argc) ramout = argv[++i];
        else if (!strcmp(argv[i], "--ram-at") && i + 1 < argc) ramat = atof(argv[++i]);
        else if (!strcmp(argv[i], "--screen") && i + 1 < argc) screenout = argv[++i];
        else if (!strcmp(argv[i], "--screen-at") && i + 1 < argc) screenat = atof(argv[++i]);
        else if (!strcmp(argv[i], "--psg-log") && i + 1 < argc) psgout = argv[++i];
        else if (!strcmp(argv[i], "--watch") && i + 1 < argc) {
            if (nwatch == MAXWATCH) {
                fprintf(stderr, "playcard: at most %d watched addresses\n", MAXWATCH);
                return 2;
            }
            watch[nwatch++] = (uint16_t)strtol(argv[++i], NULL, 0);
        }
        else if (!strcmp(argv[i], "--watch-out") && i + 1 < argc) watchout = argv[++i];
        else if (argv[i][0] != '-') {
            /* More than one card means a two-sided set, swiped in order. */
            if (ncards == MAXCARDS) {
                fprintf(stderr, "playcard: at most %d cards\n", MAXCARDS);
                return 2;
            }
            cards[ncards++] = argv[i];
        }
        else {
            fprintf(stderr, "usage: playcard card.bin [-o out.fmlog] [options]\n"
                "   --seconds N     stop after this long even if still playing "
                "(default 400)\n"
                "   --quiet-for N   silence that means the card ended "
                "(default 4)\n"
                "   --vdp-hz N      frame rate, default 50\n"
                "   --roms DIR      where the ROM images are\n"
                "   --quiet         no progress output\n"
                "   --screen F      write the cartridge's screen, as text, to F\n"
                "   --screen-at S   dump it S seconds after playback starts\n"
                "   two card files  a two-sided set, side A first: one swipe "
                "each\n"
                "   --no-fm         no FM cartridge; the UPA-01 uses the PSG\n"
                "   --psg-log F     write the PSG writes to F\n"
                "   --watch ADDR    report every read and write of ADDR "
                "(repeatable)\n"
                "   --watch-out F   where the watch report goes\n");
            return 2;
        }
    }
    if (!ncards) {
        fprintf(stderr, "usage: playcard card.bin [-o out.fmlog] [options]\n"
            "   --seconds N     stop after this long even if still playing "
            "(default 400)\n"
            "   --quiet-for N   silence that means the card ended (default 4)\n"
            "   --vdp-hz N      frame rate, default 50\n"
            "   --roms DIR      where the ROM images are\n"
            "   --screen F      write the cartridge's screen, as text, to F\n"
            "   --screen-at S   dump it S seconds after playback starts\n"
            "   --quiet         no progress output\n"
            "   two card files  a two-sided set, side A first: one swipe each\n"
            "   --no-fm         no FM cartridge; the UPA-01 uses the PSG\n"
            "   --psg-log F     write the PSG writes to F\n"
            "   --watch ADDR    report every read and write of ADDR "
            "(repeatable)\n"
            "   --watch-out F   where the watch report goes\n");
        return 2;
    }

    m = (msx *)malloc(sizeof *m);
    if (!machine_init(m, romdir, with_fm)) return 1;

    for (i = 0; i < nwatch; i++)
        m->watch[i] = watch[i];
    m->nwatch = nwatch;
    if (pcfrom >= 0.0) {
        m->pchist = (unsigned long *)calloc(0x10000, sizeof *m->pchist);
        m->pcfrom = (unsigned long)(pcfrom * CLOCK);
    }

    /*
     * Every card in turn, each followed by blank strip.  One F1 press pulls
     * one card past the head, so a two-sided set is two presses against one
     * long stream: the reader is a two-state machine and wants side A first.
     */
    m->nbits = 0;
    for (ci = 0; ci < ncards; ci++) {
        f = fopen(cards[ci], "rb");
        if (!f) { fprintf(stderr, "playcard: cannot read %s\n", cards[ci]); return 1; }
        fseek(f, 0, SEEK_END); csize[ci] = ftell(f); fseek(f, 0, SEEK_SET);
        /* A card is 433 bytes at most and has no magic number, so size is the
         * only cheap test - but it catches the whole class of "wrong file",
         * which otherwise reads in as a very long card and plays nothing. */
        if (csize[ci] < 8 || csize[ci] > 433) {
            fclose(f);
            fprintf(stderr,
                "playcard: %s is %ld bytes, and a Playcard is 433 at most.\n"
                "This does not look like a card image - check the filename.\n",
                cards[ci], csize[ci]);
            return 1;
        }
        data = (uint8_t *)malloc(csize[ci]);
        if (fread(data, 1, csize[ci], f) != (size_t)csize[ci]) {
            fclose(f);
            fprintf(stderr, "playcard: short read on %s\n", cards[ci]);
            return 1;
        }
        fclose(f);
        bitpos = start[ci] = m->nbits;
        m->nbits += csize[ci] * 8 + 4000;
        m->bits = (char *)realloc(m->bits, m->nbits + 1);
        for (k = 0; k < csize[ci] * 8; k++)
            m->bits[bitpos + k] = (data[k >> 3] >> (7 - (k & 7))) & 1 ? '1' : '0';
        memset(m->bits + bitpos + csize[ci] * 8, '0', 4000);
        free(data);
        if (!quiet) printf("%s  (%ld bytes)\n", cards[ci], csize[ci]);
    }

    run(m, 9.0, vdp_hz);                   /* boot the machine */
    if (!quiet)
        printf("  booted, %ld FM writes, %ld PSG writes\n", m->ncap, m->npsg);

    run(m, 1.0, vdp_hz);
    for (ci = 0; ci < ncards; ci++) {
        /* One press pulls one card past the head and no more: the reader has
         * to see the strip run out, or it reads straight on into the next. */
        m->bitpos = start[ci];
        m->swipe_end = start[ci] + csize[ci] * 8 + 4000;
        key(m, F1_ROW, F1_BIT, 1); run(m, 0.4, vdp_hz); key(m, F1_ROW, F1_BIT, 0);
        run(m, 6.0, vdp_hz);
        if (!quiet)
            printf("  F1: card %d read, %ld of %ld bits\n", ci + 1,
                   m->bitpos - start[ci], csize[ci] * 8 + 4000);
    }

    {
        long before = m->ncap;
        long keyons = 0;
        double played = 0.0, last_note = 0.0;
        int finished = 0;

        int srow = free_tempo ? F5_ROW : F2_ROW;
        int sbit = free_tempo ? F5_BIT : F2_BIT;

        key(m, srow, sbit, 1); run(m, 0.1, vdp_hz); key(m, srow, sbit, 0);

        if (screenout && screenat >= 0.0) {
            /* The panel is only refreshed when playback starts, so a dump
             * taken before the start key shows defaults.  This one is timed
             * from the key press. */
            run(m, screenat, vdp_hz);
            if (!dump_screen(m, screenout, screenat)) {
                fprintf(stderr, "playcard: cannot write %s\n", screenout);
                return 1;
            }
            if (!quiet)
                printf("  screen at start+%.2f s -> %s\n", screenat, screenout);
            screenout = NULL;
        }

        if (ramout) {
            /* A snapshot of the work area a moment after the start key, for
             * diffing one mode against another before the two diverge. */
            run(m, ramat, vdp_hz);
            f = fopen(ramout, "wb");
            if (!f) { fprintf(stderr, "playcard: cannot write %s\n", ramout); return 1; }
            fwrite(m->mem + 0xC000, 1, 0x4000, f);
            fclose(f);
            if (!quiet)
                printf("  RAM 0xC000-0xFFFF at start+%.2f s -> %s\n", ramat, ramout);
        }

        /*
         * Play until the card runs out, rather than for a fixed time.
         *
         * The end of a card is NOT the end of the FM traffic: once the music
         * stops the firmware keeps writing about 285 registers a second for
         * ever, housekeeping an idle chip.  What does stop, cleanly, is the
         * KEY-ONS - on a card of known length the last one lands exactly where
         * the music ends.  So the test is "no note struck for a while", and
         * `seconds` is a ceiling rather than a duration.
         */
        while (played < seconds) {
            long from = m->ncap;
            double slice = 0.25;
            run(m, slice, vdp_hz);
            played += slice;
            for (k = from; k < m->ncap; k++)
                if (m->cap[k].reg == 0x08 && ((m->cap[k].val >> 3) & 0x0F)) {
                    keyons++;
                    last_note = played;
                }
            if (keyons && played - last_note >= quiet_for) {
                finished = 1;
                break;
            }
        }

        if (!quiet) {
            printf("  %s: %ld FM register writes, %ld key-ons\n",
                   free_tempo ? "F5" : "F2", m->ncap - before, keyons);
            if (finished && free_tempo)
                printf("      stopped after %.1f s. In free tempo that is not "
                       "the end of the card:\n      it is holding for the "
                       "player's first melody note, and nothing here can "
                       "play it\n", last_note);
            else if (finished)
                printf("      the card ended after %.1f s "
                       "(no note struck for %.1f s)\n", last_note, quiet_for);
            else if (!keyons)
                printf("      nothing sounded in %.0f s\n", played);
            else
                printf("      stopped at the %.0f s ceiling, still playing "
                       "- raise --seconds\n", seconds);
        }
    }

    if (screenout) {                   /* no --screen-at: take it at the end */
        if (!dump_screen(m, screenout, 0.0)) {
            fprintf(stderr, "playcard: cannot write %s\n", screenout);
            return 1;
        }
        if (!quiet)
            printf("  screen when the card ended -> %s\n", screenout);
    }

    if (psgout) {
        f = fopen(psgout, "w");
        if (!f) { fprintf(stderr, "playcard: cannot write %s\n", psgout); return 1; }
        for (k = 0; k < m->npsg; k++)
            fprintf(f, "%.6f %02X %02X\n", m->psg[k].cyc / CLOCK,
                    m->psg[k].reg, m->psg[k].val);
        fclose(f);
        if (!quiet) printf("  PSG capture written to %s (%ld writes)\n",
                           psgout, m->npsg);
    }

    if (m->pchist) {
        /* The twenty busiest addresses.  A wait loop shows up as a handful of
         * addresses holding nearly all of the samples. */
        long total = 0, shown;
        int top;
        for (k = 0; k < 0x10000; k++)
            total += m->pchist[k];
        printf("  where the CPU sat after %.1f s (%ld samples)\n",
               m->pcfrom / CLOCK, total);
        for (shown = 0, top = 0; top < 20 && total; top++) {
            long best = -1, bi = 0;
            for (k = 0; k < 0x10000; k++)
                if ((long)m->pchist[k] > best) { best = m->pchist[k]; bi = k; }
            if (best <= 0) break;
            printf("    %04lX  %6ld  %5.1f%%\n", bi, best, 100.0 * best / total);
            m->pchist[bi] = 0;
            shown += best;
        }
    }

    if (m->nwatch) {
        f = watchout ? fopen(watchout, "w") : stdout;
        if (!f) { fprintf(stderr, "playcard: cannot write %s\n", watchout); return 1; }
        for (k = 0; k < m->ntouch; k++)
            fprintf(f, "%.6f %04X %c %02X pc=%04X\n", m->touch[k].cyc / CLOCK,
                    m->touch[k].addr, m->touch[k].write ? 'W' : 'R',
                    m->touch[k].val, m->touch[k].pc);
        if (watchout) {
            fclose(f);
            if (!quiet) printf("  %ld watched accesses written to %s\n",
                               m->ntouch, watchout);
        }
    }

    if (out) {
        f = fopen(out, "w");
        if (!f) { fprintf(stderr, "playcard: cannot write %s\n", out); return 1; }
        for (k = 0; k < m->ncap; k++)
            fprintf(f, "%.6f %02X %02X\n", m->cap[k].cyc / CLOCK,
                    m->cap[k].reg, m->cap[k].val);
        fclose(f);
        if (!quiet) printf("  capture written to %s (%ld writes)\n", out, m->ncap);
    }
    return 0;
}

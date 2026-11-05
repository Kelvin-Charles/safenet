# Draws the app icon, Android adaptive layers and splash logos into a folder:
#   uv run --no-project --with pillow python tool/make_icon.py assets/brand
# then: dart run flutter_launcher_icons && dart run flutter_native_splash:create
import sys, math
from PIL import Image, ImageDraw
OUT = sys.argv[1]
S = 4  # supersample
N = 1024 * S
NAVY_DEEP=(3,20,63); NAVY=(5,29,96); BLUE=(10,58,168); ACCENT=(46,123,255); WHITE=(255,255,255)

def bg():
    im = Image.new('RGB', (N, N))
    px = im.load()
    top, bot = NAVY, NAVY_DEEP
    # diagonal gradient deep navy -> royal blue
    a, b = NAVY_DEEP, BLUE
    for y in range(0, N, 1):
        pass
    grad = Image.linear_gradient('L').resize((N, N)).rotate(45, expand=False)
    g = Image.linear_gradient('L').resize((N, N))
    g = g.transpose(Image.Transpose.ROTATE_90)  # left->right
    g2 = Image.linear_gradient('L').resize((N, N))
    mix = Image.blend(g.convert('L'), g2, 0.5)
    im = Image.composite(Image.new('RGB',(N,N),a), Image.new('RGB',(N,N),b), mix)
    return im

def mark(d, scale=1.0, ox=0, oy=0, arc=WHITE, shield=ACCENT, lock=WHITE, hole=ACCENT):
    k = S*scale
    def P(x,y): return ((512+(x-512)*scale)*S+ox*S, (512+(y-512)*scale)*S+oy*S)
    cx, cy = 512, 600
    w = 64
    for r in (330, 230):
        x0,y0 = P(cx-r, cy-r); x1,y1 = P(cx+r, cy+r)
        d.arc([x0,y0,x1,y1], 225, 315, fill=arc, width=int(w*k))
        for ang in (225, 315):
            rr = r - w/2
            ex = cx + (r - w/2)*math.cos(math.radians(ang)); ey = cy + (r-w/2)*math.sin(math.radians(ang))
            ex, ey = P(ex, ey); cr = w/2*k
            d.ellipse([ex-cr, ey-cr, ex+cr, ey+cr], fill=arc)
    # shield (with a ring of background cut out by drawing it bigger first is skipped; arcs end above it)
    def shield_pts(grow=0):
        pts=[(512,500-grow),(640+grow,548-grow*0.4),(640+grow,640)]
        # curved bottom to point
        for t in [i/20 for i in range(1,21)]:
            x = (1-t)**2*(640+grow) + 2*(1-t)*t*(632+grow) + t*t*512
            y = (1-t)**2*640 + 2*(1-t)*t*(740+grow) + t*t*(800+grow)
            pts.append((x,y))
        left=[(1024-x,y) for x,y in reversed(pts[2:])]
        pts += left[1:] + [(384-grow,548-grow*0.4)]
        return [P(x,y) for x,y in pts]
    return shield_pts

def lockdraw(d, scale=1.0, ox=0, oy=0, lock=WHITE, hole=ACCENT):
    k=S*scale
    def P(x,y): return ((512+(x-512)*scale)*S+ox*S, (512+(y-512)*scale)*S+oy*S)
    # shackle: outer rounded rect, inner cut in the shield colour
    a=P(468,572); b=P(556,690); d.rounded_rectangle([a,b],radius=int(44*k),fill=lock)
    a=P(489,593); b=P(535,700); d.rounded_rectangle([a,b],radius=int(23*k),fill=hole)
    a=P(452,636); b=P(572,736); d.rounded_rectangle([a,b],radius=int(18*k),fill=lock)
    c=P(512,676); r=15*k; d.ellipse([c[0]-r,c[1]-r,c[0]+r,c[1]+r],fill=hole)
    a=P(504,680); b=P(520,712); d.rounded_rectangle([a,b],radius=int(6*k),fill=hole)

def full(path, scale=0.92, oy=-30, transparent=False, arc=WHITE):
    im = Image.new('RGBA',(N,N),(0,0,0,0)) if transparent else bg().convert('RGBA')
    arcs = Image.new('RGBA',(N,N),(0,0,0,0))
    sp = mark(ImageDraw.Draw(arcs), scale=scale, oy=oy, arc=arc)
    # cut a gap around the shield out of the arcs
    cut = Image.new('L',(N,N),0); cd = ImageDraw.Draw(cut)
    pts = sp(0); cd.polygon(pts, fill=255); cd.line(pts+[pts[0]], fill=255, width=int(70*S*scale), joint='curve')
    for q in pts: cd.ellipse([q[0]-35*S*scale,q[1]-35*S*scale,q[0]+35*S*scale,q[1]+35*S*scale],fill=255)
    arcs.putalpha(Image.composite(Image.new('L',(N,N),0), arcs.getchannel('A'), cut))
    im = Image.alpha_composite(im, arcs)
    d = ImageDraw.Draw(im)
    d.polygon(pts, fill=ACCENT); d.line(pts+[pts[0]], fill=ACCENT, width=int(22*S*scale), joint='curve')
    for q in pts: d.ellipse([q[0]-11*S*scale,q[1]-11*S*scale,q[0]+11*S*scale,q[1]+11*S*scale],fill=ACCENT)
    lockdraw(d, scale=scale, oy=oy)
    im = im.resize((1024,1024), Image.LANCZOS)
    if not transparent: im = im.convert('RGB')
    im.save(path)

full(OUT+'/icon.png', scale=1.0, oy=-40)                                   # iOS / legacy Android: full-bleed square
full(OUT+'/icon_fg.png', scale=1.15, oy=-46, transparent=True)   # Android adaptive foreground (safe zone)
full(OUT+'/splash.png', scale=0.9, oy=-30, transparent=True)     # splash logo on navy
full(OUT+'/splash12.png', scale=0.55, oy=-14, transparent=True)  # Android 12 circle-masked splash
im = bg().resize((1024,1024)); im.save(OUT+'/icon_bg.png')

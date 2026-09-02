import schemdraw
import schemdraw.elements as elm

with schemdraw.Drawing(show=False) as d:
    d.config(fontsize=14, lw=1.8)

    battery = elm.SourceV().up().label("OCV(SOC)", loc="left")
    d += battery

    r0 = elm.Resistor().right().label("R0")
    d += r0

    r1 = elm.Resistor().right().label("R1", loc="top")
    d += r1

    d += elm.Line().down().at(r1.start).length(1.2)
    c1 = elm.Capacitor().right().label("C1", loc="bottom").tox(r1.end)
    d += c1
    d += elm.Line().up().to(r1.end)

    d += elm.Line().right().length(1)
    d += elm.Dot(open=True).label("V_t +", loc="top")

    d += elm.Line().down().length(2.5)
    d += elm.Dot(open=True).label("V_t −", loc="right")
    d += elm.Arrow().left().length(1.2).label("I(t)", loc="top")
    d += elm.Line().tox(battery.start)
    d += elm.Line().to(battery.start)

    d.save("circuit_diagram.png", dpi=220)

print("circuit_diagram.png 저장 완료")

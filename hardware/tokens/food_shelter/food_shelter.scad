// FLOODSHIFT food & water canopy | 55 x 45 x 22 mm max
// Flat 30 x 30 mm centered ArUco pad; four canopy posts and bowl glyph frame it.
$fn=48;
union(){
  linear_extrude(3) polygon([[-27.5,-18],[-22,-22.5],[22,-22.5],[27.5,-18],[27.5,18],[22,22.5],[-22,22.5],[-27.5,18]]);
  linear_extrude(3) square([30,30],center=true);
  // Tall corner canopy posts, positioned outside the central marker square.
  for(x=[-22,22],y=[-18,18]) translate([x,y,0]) cylinder(r=1.8,h=22);
  // Bowl glyph at the south edge; open ring is printable without supports.
  translate([0,-18.5,0]) difference(){ cylinder(r=3.8,h=22); translate([0,0,-0.1]) cylinder(r=2.1,h=22.2); }
}

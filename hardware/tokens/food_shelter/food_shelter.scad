// Tagless food/water station: 55 x 45 x 22 mm limit.
$fn=48;
union() {
  linear_extrude(3) polygon([[-27.5,-18],[-22,-22.5],[22,-22.5],[27.5,-18],[27.5,18],[22,22.5],[-22,22.5],[-27.5,18]]);
  // Chunky canopy posts, no unsupported overhead sheet.
  for(x=[-22,22],y=[-17,17]) translate([x,y,0]) cylinder(r=2.5,h=22);
  // Bowl and cup have solid floors and thick vertical rims.
  translate([-9,0,2]) difference() {
    cylinder(r=10,h=9);
    translate([0,0,1]) cylinder(r=7,h=9);
  }
  translate([12,0,2]) difference() {
    cylinder(r=5.5,h=11);
    translate([0,0,1]) cylinder(r=3,h=11);
  }
  translate([18,0,2]) difference() {
    cylinder(r=4,h=8);
    translate([0,0,-0.1]) cylinder(r=1.8,h=8.2);
  }
}

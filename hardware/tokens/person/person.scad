// Tagless person: 45 x 45 x 17 mm limit; one chunky silhouette.
$fn=48;
linear_extrude(17) union() {
  // All roots overlap in area; no detached limbs or central square pad.
  translate([0,15.5]) circle(r=6.5);
  translate([-4,7]) square([8,9]);
  polygon([[-8,9],[8,9],[9,-8],[-9,-8]]);
  for(s=[-1,1]) hull() {
    translate([s*6,5]) circle(r=4);
    translate([s*18,0]) circle(r=4);
  }
  for(s=[-1,1]) hull() {
    translate([s*5,-6]) circle(r=4.5);
    translate([s*9,-17.5]) circle(r=4.5);
  }
}

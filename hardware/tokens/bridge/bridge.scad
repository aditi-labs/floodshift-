// FLOODSHIFT temporary bridge | 70 x 40 x 13 mm max
// Flat 30 x 30 mm centered ArUco pad; raised end rails create a bridge silhouette.
$fn=48;
union(){
  linear_extrude(4) square([70,22],center=true);
  for(s=[-1,1]) translate([s*25,0,0]) {
    linear_extrude(4) polygon([[-7,-11],[7,-11],[10,-20],[-10,-20]]);
    mirror([0,1,0]) linear_extrude(4) polygon([[-7,-11],[7,-11],[10,-20],[-10,-20]]);
  }
  // Upright bridge rails at both ends, clear of the marker pad.
  for(s=[-1,1]) for(y=[-8,8]) translate([s*30,y,8.5]) cube([3,4,9],center=true);
  linear_extrude(4) square([30,30],center=true);
}

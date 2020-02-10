import numpy
#rst Dimensions
# Bounding box for root airfoil
x_root_range = [-0.1, 5.1]
y_root_range = [-0.5, 0.5]
z_root = -0.01

# Bounding box for tip airfoil
x_tip_range = [7.4, 9.2]
y_tip_range = [-0.25, 0.25]
z_tip = 14.25

# Number of FFD control points per dimension
nX = 6	# streamwise
nY = 2	# perpendicular to wing planform
nZ = 8	# spanwise
#rst Compute
# Compute grid points
span_dist = numpy.linspace(0, 1, nZ)**0.8
z_sections = span_dist*(z_tip - z_root) + z_root

x_te = span_dist*(x_tip_range[0] - x_root_range[0]) + x_root_range[0]
x_le = span_dist*(x_tip_range[1] - x_root_range[1]) + x_root_range[1]
y_coords = numpy.vstack((span_dist*(y_tip_range[0] - y_root_range[0]) + y_root_range[0], span_dist*(y_tip_range[1] - y_root_range[1]) + y_root_range[1]))

X = numpy.zeros((nY*nZ, nX))
Y = numpy.zeros((nY*nZ, nX))
Z = numpy.zeros((nY*nZ, nX))
row = 0
for k in range(nZ):
    for j in range(nY):
        X[row,:] = numpy.linspace(x_te[k], x_le[k], nX)
        Y[row,:] = numpy.ones(nX)*y_coords[j,k]
        Z[row,:] = numpy.ones(nX)*z_sections[k]
        row += 1
#rst Write
# Write FFD to file
filename = "ffd.xyz"
f = open(filename, 'w')
f.write('\t\t1\n')
f.write('\t\t%d\t\t%d\t\t%d\n' % (nX, nY, nZ))
for set in [X,Y,Z]:
    for row in set:
        vals = tuple(row)
        f.write('\t%3.8f\t%3.8f\t%3.8f\t%3.8f\t%3.8f\t%3.8f\n' % vals)
f.close()
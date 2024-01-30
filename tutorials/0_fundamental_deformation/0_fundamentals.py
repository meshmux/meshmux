'''
The purpose of this excercise is to demonstrate Harmonic mesh extension:
Shamanskiy, A., Simeon, B. Mesh moving techniques in fluid-structure interaction: robustness, accumulated distortion and computational efficiency. Comput Mech 67, 583–600 (2021). https://doi.org/10.1007/s00466-020-01950-x
We solve Laplace's equation on the reference domain to calculate pointwise mesh deformation based on the specified mesh deformation on the boundary.

In this example, we consider unit square as the reference domain \Omega. We apply specified mesh displacement on the top (\Gamma_{top} \subset \partial \Omega) and bottom (\Gamma_{bottom}\subset \partial \Omega) boundaries and use Harmonic mesh extension to propoagate the displacement inside the domain.

Reference domain: \Omega = [0, 1]^2 (Unit square)
Solve Laplace's equation:
- \Delta u = 0 \ , \ \text{in} \Omega \ ,
B.C.s ((x, y) \in \Omega):
On bottom boundary (\Gamma_1 \cup \Gamma_5): u = (0., 0.2 * sin(2 \pi x)) \ , (Specified mesh displacement) \\
On top boundary (\Gamma_9 \cup \Gamma_{12}): u = (0., 0.1 * sin(2 \pi x)) \ , (Specified mesh displacement) \\
On left and right boundaries (\Gamma_4 \cup \Gamma_6 \cup \Gamma_{10} \cup \Gamma_{11}):
u = (0., 0.)

The deformed domain \tilde{\Omega} is given by:
\tilde{x} = x + u \ , \ \tilde{x} \in \tilde{\Omega} \ , \ x \in \Omega \ .
'''

from mpi4py import MPI
from petsc4py import PETSc

import ufl
import dolfinx
from dolfinx.fem.petsc import assemble_matrix, assemble_vector, \
    apply_lifting, set_bc

import numpy as np

# Read REFERENCE mesh
mesh_comm = MPI.COMM_WORLD
gdim = 2
gmsh_model_rank = 0
mesh, subdomains, boundaries = \
    dolfinx.io.gmshio.read_from_msh("mesh_data/mesh.msh",
                                     mesh_comm, gmsh_model_rank,
                                     gdim=gdim)

# Store REFERENCE mesh coordinates
reference_coordinates = mesh.geometry.x.copy()

# Define the VectorFunctionSpace with same degree as the mesh degree
mesh_degree = mesh.geometry.cmaps[0].degree
V = dolfinx.fem.VectorFunctionSpace(mesh, ("CG", mesh_degree))
u = ufl.TrialFunction(V)
v = ufl.TestFunction(V)

# Define mesh deformation on boundaries (boundary conditions)
bc_list = []

# Bottom boundaries (Boundary markers 1 and 5)
def bc_bottom(x):
    return (0. * x[0], 0.2 * np.sin(x[0] * 2 * np.pi))


# Top boundaries (Boundary markers 9 and 12)
def bc_top(x):
    return (0. * x[0], 0.1 * np.sin(x[0] * 2 * np.pi))


# Side boundaries (Boundary markers 4, 6, 10 and 11)
def bc_side(x):
    return (0. * x[0], 0. * x[1])


# We gather boundary markers and boundary displacements
# in respective orders as list and specify boundary conditions
bc_markers = [1, 5, 9, 12, 4, 6, 10, 11]
bc_function_list = \
    [bc_bottom, bc_bottom, bc_top, bc_top, bc_side, bc_side, bc_side, bc_side]
for i in range(len(bc_markers)):
    dofs = boundaries.find(bc_markers[i])
    bc_dofs = dolfinx.fem.locate_dofs_topological(V, gdim-1, dofs)
    bc_func = dolfinx.fem.Function(V)
    bc_func.interpolate(bc_function_list[i])
    bc_list.append(dolfinx.fem.dirichletbc(bc_func, bc_dofs))
# bc_list now contains boundary conditions


'''
# NOTE
It is important to define ZERO DIRICHLET boundary conditions, else
these boundaries are considered as zero NEUMANN boundary conditions
'''

# We now solve Laplace's equation on the REFERENCE mesh
a_form = dolfinx.fem.form(ufl.inner(ufl.grad(u), ufl.grad(v))*ufl.dx)
l_form = \
    dolfinx.fem.form(ufl.inner(dolfinx.fem.Constant
                               (mesh, PETSc.ScalarType((0.,) * mesh.geometry.dim)),
                               v) * ufl.dx)

uh = dolfinx.fem.Function(V)
A = assemble_matrix(a_form, bcs=bc_list)
A.assemble()
F = assemble_vector(l_form)
dolfinx.fem.petsc.apply_lifting(F, [a_form], [bc_list])
F.ghostUpdate(addv=PETSc.InsertMode.ADD, mode=PETSc.ScatterMode.REVERSE)
dolfinx.fem.petsc.set_bc(F, bc_list)
ksp = PETSc.KSP()
ksp.create(mesh.comm)
ksp.setOperators(A)
ksp.setType("preonly")
ksp.getPC().setType("lu")
ksp.getPC().setFactorSolverType("mumps")
ksp.setFromOptions()
ksp.solve(F, uh.vector)
uh.x.scatter_forward()

# uh now corresponds to the displacement of each node.
# We overwrite mesh cordinates with displacement uh
mesh.geometry.x[:, :mesh.geometry.dim] += \
    uh.x.array.reshape(reference_coordinates.shape[0], gdim)


with dolfinx.io.XDMFFile(mesh.comm,
                        f"deformed_mesh_data/deformed_mesh.xdmf",
                        "w") as mesh_file_xdmf:
    mesh_file_xdmf.write_mesh(mesh)
    mesh_file_xdmf.write_meshtags(subdomains, mesh.geometry)
    mesh_file_xdmf.write_meshtags(boundaries, mesh.geometry)

# Restoring to REFERENCE mesh configuration
# We overwrite mesh cordinates with reference_coordinates
mesh.geometry.x[:] = reference_coordinates

# Instead of solving Laplace's equation,
# one can also solve linear elasticity equation.

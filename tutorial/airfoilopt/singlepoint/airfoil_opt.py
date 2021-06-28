# ======================================================================
#         Import modules
# ======================================================================
# rst Imports (beg)
import os
import numpy as np
from mpi4py import MPI
from baseclasses import AeroProblem
from adflow import ADFLOW
from pygeo import DVGeometry, DVConstraints
from pyoptsparse import Optimization, OPT
from idwarp import USMesh
from multipoint import multiPointSparse
import argparse



def ksAgg(g, rho=1.0):
    """Compute a smooth approximation to the maximum of a set of values us KS agregation
    Parameters
    ----------
    g : 1d array
        Values to approximate the maximum of
    rho : float, optional
        KS Weight parameter, larger values give a closer but less smooth approximation of the maximum, by default 100.0
    Returns
    -------
    float
        The KS agregated value
    """
    maxg = np.max(g)
    return maxg + 1.0 / rho * np.log(np.sum(np.exp(rho * (g - maxg))))


parser = argparse.ArgumentParser()

# Problem/task options
parser.add_argument("--mach", type=float, default=0.75)
parser.add_argument("--output", type=str, default="output")
parser.add_argument("--cl", type=float, default=0.5)
parser.add_argument("--alt", type=int, default=1e4)
parser.add_argument("--preTrim", action="store_true", dest="preTrim", default=False)
parser.add_argument("--volCon", action="store_true", dest="volCon", default=False)
parser.add_argument("--volUpper", type=float, default=0.07)
parser.add_argument("--volLower", type=float, default=0.064837137176294343)
parser.add_argument("--tcMin", type=float, default=0.12)
parser.add_argument("--zeroLift", action="store_true", dest="zeroLift", default=False)
parser.add_argument("--relThickLower", type=float, default=0.1)
parser.add_argument("--absThickLower", type=float, default=0.00035)
args=parser.parse_args()

if args.zeroLift and args.cl!=0.:
    args.cl = 0.
elif not args.zeroLift and args.cl==0.:
    args.zeroLift=True

outputDirectory = args.output

# rst Imports (end)
# ======================================================================
#         Create multipoint communication object
# ======================================================================
# rst multipoint (beg)
MP = multiPointSparse(MPI.COMM_WORLD)
MP.addProcessorSet("cruise", nMembers=1, memberSizes=MPI.COMM_WORLD.size)
comm, setComm, setFlags, groupFlags, ptID = MP.createCommunicators()
if comm.rank == 0:
    os.system(f"mkdir -p {outputDirectory}")
# rst multipoint (end)
# ======================================================================
#         ADflow Set-up
# ======================================================================
# rst adflow (beg)
aeroOptions = {
    # Common Parameters
    "gridFile": "../mesh/n0012.cgns",
    "outputDirectory": outputDirectory,
    # Physics Parameters
    "equationType": "RANS",
    "smoother": "DADI",
    "MGCycle": "3w",
    "nCycles": 20000,
    "nCyclesCoarse": 250,
    "monitorvariables": ["resrho", "cl", "cd", "cmz", "yplus"],
    "useNKSolver": True,
    "useanksolver": True,
    "nsubiterturb": 10,
    "liftIndex": 2,
    "infchangecorrection": True,
    "RKReset": False,
    "nRKReset": 5,
    # "ANKSwitchTol":1e-2,
    # "ANKSecondOrdSwitchTol":1e-4,
    # "ANKCoupledSwitchTol":1e-5,
    # Convergence Parameters
    "L2Convergence": 1e-15,
    "L2ConvergenceCoarse": 1e-4,
    # Adjoint Parameters
    "adjointSolver": "GMRES",
    "adjointL2Convergence": 1e-12,
    "ADPC": True,
    "adjointMaxIter": 5000,
    "adjointSubspaceSize": 400,
    "ILUFill": 3,
    "ASMOverlap": 3,
    "outerPreconIts": 3,
    "NKSubSpaceSize": 400,
    "NKASMOverlap": 4,
    "NKPCILUFill": 4,
    "NKJacobianLag": 5,
    "nkswitchtol": 1e-6,
    "nkouterpreconits": 3,
    "NKInnerPreConIts": 3,
    "writeSurfaceSolution": False,
    "writeVolumeSolution": False,
    "writeTecplotSurfaceSolution": True,
    "frozenTurbulence": False,
    "restartADjoint": True,
    "lowSpeedPreconditioner": args.mach<0.5,
}

# Create solver
CFDSolver = ADFLOW(options=aeroOptions, comm=comm)
# CFDSolver.addLiftDistribution(200, "z")
# rst adflow (end)
# ======================================================================
#         Set up flow conditions with AeroProblem
# ======================================================================
# rst aeroproblem (beg)
alpha0 = 0. if args.zeroLift else 1.0
ap = AeroProblem(
    name="fc",
    alpha=np.clip(alpha0, -4.0, 4.0),
    mach=args.mach,
    altitude=args.alt,
    areaRef=1.0,
    chordRef=1.0,
    evalFuncs=["cl", "cd"],
)

# --- Optionally do a trim solve so that we start at the right CL ---
if args.preTrim and not args.zeroLift:
    CFDSolver.solveCL(ap, args.cl, delta=0.1, tol=1e-4, autoReset=False)

if not args.zeroLift:
    # Add angle of attack variable
    ap.addDV("alpha", lower=-10.0, upper=10.0, scale=1.0)
# rst aeroproblem (end)
# ======================================================================
#         Geometric Design Variable Set-up
# ======================================================================
# rst dvgeo (beg)
# Create DVGeometry object
FFDFile = "../ffd/ffd.xyz"

DVGeo = DVGeometry(FFDFile)
DVGeo.addGeoDVLocal("shape", lower=-0.05, upper=0.05, axis="y", scale=1.0)

span = 1.0
pos = np.array([0.5]) * span
CFDSolver.addSlices("z", pos, sliceType="absolute")

# Add DVGeo object to CFD solver
CFDSolver.setDVGeo(DVGeo)
# rst dvgeo (end)
# ======================================================================
#         DVConstraint Setup
# ======================================================================
# rst dvcon (beg)

DVCon = DVConstraints()
DVCon.setDVGeo(DVGeo)

# Only ADflow has the getTriangulatedSurface Function
DVCon.setSurface(CFDSolver.getTriangulatedMeshSurface())

# Le/Te constraints
lIndex = DVGeo.getLocalIndex(0)
indSetA = []
indSetB = []
for k in range(0, 1):
    indSetA.append(lIndex[0, 0, k])  # all DV for upper and lower should be same but different sign
    indSetB.append(lIndex[0, 1, k])
for k in range(0, 1):
    indSetA.append(lIndex[-1, 0, k])
    indSetB.append(lIndex[-1, 1, k])
DVCon.addLeTeConstraints(0, indSetA=indSetA, indSetB=indSetB)

# DV should be same along spanwise
lIndex = DVGeo.getLocalIndex(0)
indSetA = []
indSetB = []
for i in range(lIndex.shape[0]):
    indSetA.append(lIndex[i, 0, 0])
    indSetB.append(lIndex[i, 0, 1])
for i in range(lIndex.shape[0]):
    indSetA.append(lIndex[i, 1, 0])
    indSetB.append(lIndex[i, 1, 1])
DVCon.addLinearConstraintsShape(indSetA, indSetB, factorA=1.0, factorB=-1.0, lower=0, upper=0)

le = 0.0001
leList = [[le, 0, le], [le, 0, 1.0 - le]]
teList = [[1.0 - le, 0, le], [1.0 - le, 0, 1.0 - le]]

if args.volCon:
    DVCon.addVolumeConstraint(leList, teList, 2, 100, lower=args.volLower, upper=args.volUpper, scaled=False)

DVCon.addThicknessConstraints2D(
    leList, teList, 2, 100, scaled=False, addToPyOpt=False
)  # These thickness constraints are not applied directly, they are used for the KSThickness constraint
DVCon.addThicknessConstraints2D(leList, teList, 2, 100, lower=args.relThickLower, upper=3.0)
DVCon.addThicknessConstraints2D(leList, teList, 2, 100, lower=args.absThickLower, upper=3.0, scaled=False)

if comm.rank == 0:
    fileName = os.path.join(outputDirectory, "constraints.dat")
    DVCon.writeTecplot(fileName)
# rst dvcon (end)
# ======================================================================
#         Mesh Warping Set-up
# ======================================================================
# rst warp (beg)
meshOptions = {"gridFile": "../mesh/n0012.cgns"}

mesh = USMesh(options=meshOptions, comm=comm)
CFDSolver.setMesh(mesh)
# rst warp (end)
# ======================================================================
#         Functions:
# ======================================================================
# rst funcs (beg)
def cruiseFuncs(x):
    if MPI.COMM_WORLD.rank == 0:
        print(x)
    # Set design vars
    DVGeo.setDesignVars(x)
    ap.setDesignVars(x)
    # Run CFD
    CFDSolver(ap)
    # Evaluate functions
    funcs = {}
    DVCon.evalFunctions(funcs)
    CFDSolver.evalFunctions(ap, funcs)
    CFDSolver.checkSolutionFailure(ap, funcs)
    if funcs["fail"]:
        CFDSolver.resetFlow(ap)
    if MPI.COMM_WORLD.rank == 0:
        print(funcs)
    return funcs


def cruiseFuncsSens(x, funcs):
    funcsSens = {}
    DVCon.evalFunctionsSens(funcsSens)
    CFDSolver.evalFunctionsSens(ap, funcsSens)
    CFDSolver.checkAdjointFailure(ap, funcsSens)
    if funcsSens["fail"]:
        CFDSolver.resetAdjoint(ap)
    if MPI.COMM_WORLD.rank == 0:
        print(funcsSens)
    return funcsSens


def objCon(funcs, printOK, passThroughFuncs):
    # Assemble the objective and any additional constraints:
    funcs["obj"] = funcs[ap["cd"]]
    funcs["cl_con_" + ap.name] = funcs[ap["cl"]] - args.cl
    funcs["KSThickness"] = ksAgg(funcs["DVCon1_thickness_constraints_0"], rho=1e4)
    if printOK:
        print("funcs in obj:", funcs)
    return funcs


# rst funcs (end)
# ======================================================================
#         Optimization Problem Set-up
# ======================================================================
# rst optprob (beg)
# Create optimization problem
optProb = Optimization("opt", MP.obj, comm=MPI.COMM_WORLD)

# Add objective
optProb.addObj("obj", scale=1e4)

# Add variables from the AeroProblem
ap.addVariablesPyOpt(optProb)

# Add DVGeo variables
DVGeo.addVariablesPyOpt(optProb)

# Add constraints
DVCon.addConstraintsPyOpt(optProb)
optProb.addCon("cl_con_" + ap.name, lower=0.0, upper=0.0, scale=1.0)
optProb.addCon("KSThickness", lower=args.tcMin, scale=1.0 / args.tcMin, wrt="shape")

# The MP object needs the 'obj' and 'sens' function for each proc set,
# the optimization problem and what the objcon function is:
MP.setProcSetObjFunc("cruise", cruiseFuncs)
MP.setProcSetSensFunc("cruise", cruiseFuncsSens)
MP.setObjCon(objCon)
MP.setOptProb(optProb)
optProb.printSparsity()
# rst optprob (end)
# rst optimizer
# Set up optimizer
optimizer = "SNOPT"
if optimizer == "SLSQP":
    optOptions = {"IFILE": os.path.join(outputDirectory, "SLSQP.out")}
    opt = OPT("slsqp", options=optOptions)
elif optimizer == "SNOPT":
    optOptions = {
        "Major feasibility tolerance": 1e-4,
        "Major optimality tolerance": 1e-4,
        "Difference interval": 1e-5,
        "Hessian full memory": None,
        "Function precision": 1e-8,
        "Print file": os.path.join(outputDirectory, "SNOPT_print.out"),
        "Summary file": os.path.join(outputDirectory, "SNOPT_summary.out"),
        "Nonderivative linesearch": None,
        "Verify level": 0,
        "Major step limit": 0.5,
    }
    opt = OPT("snopt", options=optOptions)

# Run Optimization
sol = opt(optProb, MP.sens, storeHistory=os.path.join(outputDirectory, "opt.hst"))
if MPI.COMM_WORLD.rank == 0:
    print(sol)

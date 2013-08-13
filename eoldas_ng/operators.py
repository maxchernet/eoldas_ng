#!/usr/bin/env python
"""
EOLDAS ng
==========

A reorganisation of the EOLDAS codebase

"""

import numpy as np
import scipy.optimize
from collections import OrderedDict

FIXED = 1
CONSTANT = 2
VARIABLE = 3

class State ( object ):
    
    """A state-definition class
    
    
       In EO-LDAS, the state requires the following:
        
       1. a configuration dictionary,
       2. a state grid
       3. a dictionary with default parameter values
        
       The state grid is an array that defines the domain of the
       problem. For example, for a temporal DA problem, it will be
       a vector of however many elements are required timesteps. For
       a spatial problem, it will be a 2D array with the locations
       of the gridcells. the configuration diciontary stores whether a
       particular parameter is variable over the grid (i.e. is this
       parameter estimated for all timesteps or grid positions?),
       constant (so it is constant in time and/or space), or whether we
       just prescribe some default value."""
       
    def __init__ ( self, state_config, state_grid, default_values, \
            parameter_min, parameter_max ):
        """State constructor
        
        
        """
        self.state_config = state_config
        self.state_grid = state_grid
        self.n_elems =  self.state_grid.size
        self.default_values = default_values
        self.operators = {}
        self.n_params = self._state_vector_size ()
        self.parameter_min = parameter_min
        self.parameter_max = parameter_max
        self.bounds = []
        for ( i, param ) in enumerate ( self.state_config.iterkeys() ):
            self.bounds.append ( [ self.parameter_min[param], \
                self.parameter_max[param] ] )
        
    def set_transformations ( self, transformation_dict, \
            invtransformation_dict ):
        """We can set transformations to the data that will be
        applied automatically when required."""
        self.transformation_dict = transformation_dict
        self.invtransformation_dict = invtransformation_dict
        # Recalculate boundaries
        self.bounds = []
        for ( i, param ) in enumerate ( self.state_config.iterkeys() ):
            if transformation_dict.has_key ( param ):
                tmin = transformation_dict[param] ( self.parameter_min[param] )
                tmax = transformation_dict[param] ( self.parameter_max[param] )
            else:
                tmin = self.parameter_min[param]
                tmax = self.parameter_max[param]
            if tmin > tmax:
                self.bounds.append ([ tmax, tmin ] )
            else:
                self.bounds.append ([ tmin, tmax ] )
                
                
    def _state_vector_size ( self ):
        n_params = 0
        for param, typo in self.state_config.iteritems():
            if typo == CONSTANT:
                n_params  += 1
            elif typo == VARIABLE:
                n_params  += self.n_elems
        return n_params
        
    def pack_from_dict ( self, x_dict ):
        the_vector = np.zeros ( self.n_params )
        # Now, populate said vector in the right order
        # looping over state_config *should* preserve the order
        i = 0
        for param, typo in self.state_config.iteritems():
            if typo == CONSTANT: # Constant value for all times
                the_vector[i] = x_dict[param]
                i = i+1        
            elif typo == VARIABLE:
                # For this particular date, the relevant parameter is at location iloc
                the_vector[i:(i + self.n_elems)] =  x_dict[param]
                i += self.n_elems
        return the_vector 
    
    def _unpack_to_dict ( self, x ):
        """Unpacks an optimisation vector `x` to a working dict"""
        the_dict = OrderedDict()
        i = 0
        for param, typo in self.state_config.iteritems():
            
            if typo == FIXED: # Default value for all times
                the_dict[param] = self.default_values[param]
                
            elif typo == CONSTANT: # Constant value for all times
                if self.invtransformation_dict.has_key ( param ):
                    the_dict[param] = self.invtransformation_dict[param]( x[i] )
                else:
                    the_dict[param] = x[i]
                i += 1
                
            elif typo == VARIABLE:
                if self.invtransformation_dict.has_key ( param ):
                    the_dict[param] = self.invtransformation_dict[param] ( \
                        x[i:(i+self.n_elems)]).reshape( \
                        self.state_grid.shape )
                else:
                    the_dict[param] = x[i:(i+self.n_elems)].reshape( \
                        self.state_grid.shape )
                i += self.n_elems
            
        return the_dict
    
    def add_operator ( self, op_name, op ):
         """Add operators to the state class
         
         This method will add operator classes (e.g. objects with a `der_cost` and a
         `der_der_cost` method)"""
         the_op = getattr( op, "der_cost", None)
         if not callable(the_op):
             raise AttributeError, "%s does not have a der_cost method!" % op_name     
         self.operators[ op_name ] = op
     
    def optimize ( self, x0 ):
        
        """Optimise the state starting from a first guess `x0`"""
        if type(x0) == type ( {} ):
            x0 = self.pack_from_dict ( x0 )
            
        retval = scipy.optimize.fmin_l_bfgs_b( self.cost, x0, disp=1 )
        return retval
     
    def cost ( self, x ):
         """Calculate the cost function using a flattened state vector representation"""
         x_dict = self._unpack_to_dict ( x )
         aggr_cost = 0
         aggr_der_cost = x*0.0
         for op_name, the_op in self.operators.iteritems():
             cost, der_cost = the_op.der_cost ( x_dict, self.state_config )
             print op_name, cost, der_cost.shape, aggr_cost
             aggr_cost = aggr_cost + cost
             aggr_der_cost = aggr_der_cost + der_cost
         return aggr_cost, aggr_der_cost
         
##################################################################################        
##################################################################################        

class Prior ( object ):
    """A gaussian prior class"""
    def __init__ ( self, prior_mu, prior_inv_cov ):
        """The prior constructor.
        
        We take a dictionary with means and inverse covariance structures. The elements
        of the dictionary can either be 1-element or several element arrays (so you 
        could have an estimate of LAI for each time step from climatology, or a
        single value). The inverse covariance (or precision) matrix is either a single
        value ($1/\sigma^{2}$), or a full matrix. If you pass a single value for a
        VARIABLE parameter, it will be converted into a diagonal matrix automatically"""
        self.mu = prior_mu
        self.inv_cov = prior_inv_cov
        
                    
    
    def der_cost ( self, x_dict, state_config ):
        """Calculate the cost function and its partial derivatives for the prior object
        
        Takes a parameter dictionary, and a state configuration dictionary"""
        i = 0
        cost = 0
        
        n = 0
        for param, typo in state_config.iteritems():
            if typo == CONSTANT:
                n += 1
            elif typo == VARIABLE:
                n_elems = len ( x_dict[param] )
                n += n_elems
        der_cost = np.zeros ( n )
        for param, typo in state_config.iteritems():
            
            if typo == FIXED: # Default value for all times
                # Doesn't do anything so we just skip
                pass
                
            if typo == CONSTANT: # Constant value for all times
                
                cost = cost + 0.5*( x_dict[param] - self.mu[param])**2*self.inv_cov[param]
                der_cost[i] = ( x_dict[param] - self.mu[param])*self.inv_cov[param]
                
                i += 1                
                
            elif typo == VARIABLE:
                
                if self.inv_cov[param].size == 1:
                    sigma = self.inv_cov[param]
                    self.inv_cov[param] = np.diag( np.ones(n_elems)*sigma )
                cost_m = ( x_dict[param] - self.mu[param]).dot ( self.inv_cov[param] )
                cost = cost + 0.5*(cost_m*(x_dict[param] - self.mu[param])).sum()
                der_cost[i:(i+n_elems)] = cost_m                                         
                
                i += n_elems
                
        return cost, der_cost
    
    def der_der_cost ( self ):
        pass
    
    

class TemporalSmoother ( object ):
    """A temporal smoother class"""
    def __init__ ( self, state_grid, order=1, gamma=None ):
        self.order = order
        self.n_elems = state_grid.shape[0]
        I = np.identity( state_grid.shape[0] )
        self.D1 = np.matrix(I - np.roll(I,1))
        self.gamma = gamma
    def der_cost ( self, x_dict, state_config ):
        """Calculate the cost function and its partial derivs for a time smoother
        
        Takes a parameter dictionary, and a state configuration dictionary"""
        i = 0
        cost = 0
        n = 0
        if x_dict.has_key ( 'gamma' ):
            self.gamma = x_dict['gamma']
            x_dict.pop ( 'gamma' )
        n = 0
        for param, typo in state_config.iteritems():
            if typo == CONSTANT:
                n += 1
            elif typo == VARIABLE:
                n_elems = len ( x_dict[param] )
                n += n_elems
        der_cost = np.zeros ( n )

        for param, typo in state_config.iteritems():
            
            if typo == FIXED: # Default value for all times
                # Doesn't do anything so we just skip
                pass
                
            if typo == CONSTANT: # Constant value for all times
                # No model constraint!
                               
                i += 1                
                
            elif typo == VARIABLE:
                xa = np.matrix ( x_dict[param] )
                cost = cost + 0.5*self.gamma*np.dot((self.D1*(xa.T)).T, self.D1*xa.T)
                der_cost[i:(i+self.n_elems)] = np.array(self.gamma*np.dot((self.D1).T, self.D1*xa.T)).squeeze()                
                i += self.n_elems
                
        return cost, der_cost
    
    def der_der_cost ( self ):
        """The Hessian (rider)"""
        return self.gamma*np.dot ( self.D1,np.eye( self.n_elems )).dot( self.D1.T)
            

class ObservationOperator ( object ):
    """An Identity observation operator"""
    def __init__ ( self, observations, sigma_obs, mask):
        self.observations = observations
        self.sigma_obs = sigma_obs
        self.mask = mask
        self.n_elems = observations.shape[0]
        
    def der_cost ( self, x_dict, state_config ):
        """Calculate the cost function and its partial derivs for identity obs op
        
        Takes a parameter dictionary, and a state configuration dictionary"""
        i = 0
        cost = 0
        n = 0
        
        for typo in x_dict.iteritems():
            if np.isscalar ( typo[1] ):
                n = n + 1
            else:
                n = n + len ( typo[1] )
        der_cost = np.zeros ( n )
        for param, typo in state_config.iteritems():
            
            if typo == FIXED: # Default value for all times
                # Doesn't do anything so we just skip
                pass
                
            if typo == CONSTANT: # Constant value for all times
                # No model constraint!
                               
                i += 1                
                
            elif typo == VARIABLE and param == "magnitude":
                cost = cost + 0.5*np.sum((self.observations[self.mask] - x_dict[param][self.mask])**2/self.sigma_obs**2)
                der_cost[i:(i+self.n_elems)][self.mask] = -(self.observations[self.mask] - x_dict[param][self.mask])/self.sigma_obs**2
                i += self.n_elems
            elif typo == VARIABLE and param != "magnitude":
                i += self.n_elems
                
        return cost, der_cost
        

class ObservationOperatorGP ( object ):
    """An Identity observation operator"""
    def __init__ ( self, state_grid, observations, emulators, default_values, bu, bandpass ):
        
        
        self.observations = observations
        self.n_elems = self.observations.shape[0]
        self.state_grid = state_grid
        self.emulators = emulators
        self.default_values = default_values
        self.bandpass = bandpass
        self.bu = bu
        
    def der_cost ( self, x_dict, state_config ):
        """Calculate the cost function and its partial derivs for identity obs op
        
        Takes a parameter dictionary, and a state configuration dictionary"""
        i = 0
        cost = 0
        n = 0
        
        for typo in x_dict.iteritems():
            if np.isscalar ( typo[1] ):
                n = n + 1
            else:
                n = n + len ( typo[1] )
        der_cost = np.zeros ( n )
        for (idoy_pos, obs_doy ) in enumerate ( self.observations[:,0] ): # This will probably need to be changed
            # Each day has a different acquisition geometry, so we need
            # to find the relvant emulator. In this case
            emulator_key = "emulator_%08.4Gx%08.4Gx%08.4G.npz" % ( self.observations[idoy_pos, [1] ], \
                self.observations[idoy_pos, [2] ], self.observations[idoy_pos, [3] ])
            # This is the location of obs_doy in the state grid
            iloc = self.state_grid == obs_doy
            # The full state for today will be put together as a dictionary
            this_doy_dict = {}
            # Now loop over all parameters
            for param, typo in state_config.iteritems():
            
                if typo == FIXED: # Default value for all times
                    # 
                    this_doy_dict[param] = self.default_values[param]
                    
                if typo == CONSTANT: # Constant value for all times
                    # We should get a single scalar from x_dict here
                    this_doy_dict[param] = x_dict[param]               

                    
                elif typo == VARIABLE:
                    # For this particular date, the relevant parameter is at location iloc
                    this_doy_dict[param] = x_dict[param][iloc]
            # Now, translate the dictionary to an array or something
            # I'm hoping that x_dict is an ordered dict, so that the keys are in
            # prosail-friendly order
            x_today = [ this_doy_dict[param] \
                    for param in x_dict.iterkeys() ]
            fwd_model, der_fwd_model = self.emulators[emulator_key].predict ( x_today )
            rho = fwd_model.dot(self.bandpass.T)/(self.bandpass.sum(axis=1))
            # Now, the cost is straightforward
            residuals = rho - self.observations[idoy_pos, 4+i] 
            cost += 0.5*residuals**2/self.bu**2
            #############################
            ### DERIVATIVE NOT YET DONE
            ### der_fwd_model is (11, 2101), so need to apply bandpass functions etc
            ###
            the_derivatives = der_fwd_model.dot ( residuals ) # or something
            i = 0
            for param, typo in state_config.iteritems():
                if typo == CONSTANT: # Constant value for all times
                    der_cost[i] += the_derivatives[i]
                    i += 1        
                elif typo == VARIABLE:
                    #For this particular date, the relevant parameter is at location iloc
                    der_cost[i + i_loc ] =  the_derivatives[i] # vector
                    i += self.state_grid.size # will this work for 1d and 2d?
        return cost, der_cost

                



##################################################################################        
##################################################################################              
if __name__ == "__main__":

    # Test the above classes, also demonstrate set up
    
    # First, define the state configuration dictionary
    state_config = OrderedDict ()
    state_config['bsoil'] = CONSTANT
    state_config['cbrown'] = VARIABLE
    state_config['hspot'] = CONSTANT
    state_config['n'] = CONSTANT
    state_config['psoil'] = VARIABLE
    state_config['ala'] = CONSTANT
    state_config['cab'] = VARIABLE
    state_config['car'] = CONSTANT
    state_config['cm'] = VARIABLE
    state_config['cw'] = VARIABLE
    state_config['lai'] = VARIABLE
    
    # Now define the default values
    default_par = OrderedDict ()
    default_par['bsoil'] = 1.
    default_par['cbrown'] = 0.01
    default_par['hspot'] = 0.01
    default_par['n'] = 1.5
    default_par['psoil'] = 0.1
    default_par['ala'] = 45.
    default_par['cab'] = 40.
    default_par['car'] = 10.
    default_par['cm'] = 0.0065 # Say?
    default_par['cw'] = 0.018 # Say?
    default_par['lai'] = 2
    # Define boundaries
    parameter_names = [ 'bsoil', 'cbrown', 'hspot', 'n', \
        'psoil', 'ala', 'cab', 'car', 'cm', 'cw', 'lai' ]
    parameter_min = OrderedDict()
    parameter_max = OrderedDict()
    min_vals = [ 0., 0., 0.001, 0.8, 0., 0., 0.2, 0., 0.0017, 0.0043, 0.001 ]
    max_vals = [ 2., 1., 0.999, 2.5, 1., 90., 77., 25., 0.0331, 0.0713, 15 ]
    for i, param in enumerate ( parameter_names ):
        parameter_min[param] = min_vals[i]
        parameter_max[param] = max_vals[i]
    # Define the state grid. In time in this case
    state_grid = np.arange ( 1, 366 )
    # Define parameter transformations
    transformations = {
        'lai': lambda x: np.exp ( -x/2. ), \
        'cab': lambda x: np.exp ( -x/100. ), \
        'car': lambda x: np.exp ( -x/100. ), \
        'cw': lambda x: np.exp ( -50.*x ), \
        'cm': lambda x: np.exp ( -100.*x ), \
        'ala': lambda x: x/90. }
    inv_transformations = {
        'lai': lambda x: -2*np.log ( x ), \
        'cab': lambda x: -100*np.log ( x ), \
        'car': lambda x: -100*np.log( x ), \
        'cw': lambda x: (-1/50.)*np.log ( x ), \
        'cm': lambda x: (-1/100.)*np.log ( x ), \
        'ala': lambda x: 90.*x }
    
    # Define the state
    # L'etat, c'est moi
    state = State ( state_config, state_grid, default_par, \
        parameter_min, parameter_max )
    # Set the transformations
    state.set_transformations ( transformations, inv_transformations )

    
    bsoil = 1.2
    cbrown = 0.4*(1-np.cos(2*np.pi*state_grid/365.))
    hspot = 0.01
    n = 2.1
    psoil = 0.5*(1-np.cos(2*np.pi*state_grid/365.))
    ala = state.transformation_dict['ala'](45.)
    cab = state.transformation_dict['cab'](80*(1-np.cos(2*np.pi*state_grid/365.)))
    car = state.transformation_dict['car'](1.)
    cm = state.transformation_dict['cm'](0.0017*(1-np.cos(2*np.pi*state_grid/365.)))
    cw = state.transformation_dict['cw'](0.03*(1-np.cos(2*np.pi*state_grid/365.)))
    lai = state.transformation_dict['lai'](4.0*(1-np.cos(2*np.pi*state_grid/365.)))
    
    x = np.r_[ bsoil, cbrown, hspot, n, psoil, ala, cab, car, cm, cw, lai ]
    # Get the original responses by
    # lai_traj = state._unpack_to_dict(x )['lai']
    s = state._unpack_to_dict ( x )

            
    mu_prior = OrderedDict ()
    prior_inv_cov = OrderedDict ()
    for param in parameter_names:
        mu_prior[param] = np.array([default_par[param]])
        prior_inv_cov[param] = np.array(parameter_max[param] - parameter_min[param]*0.4)
    prior = Prior ( mu_prior, prior_inv_cov )
    cost, der_cost = prior.der_cost ( s, state_config )
    
    
    gamma = 10.
    smoother_time = TemporalSmoother ( state_grid, gamma=gamma)
    cost, der_cost = smoother_time.der_cost ( s, state_config )
    #print cost
    #print der_cost
    #s['lai'] = 5.*np.ones_like ( state_grid )
    #cost, der_cost = smoother_time.der_cost ( s, state_config )
    #print cost
    #print der_cost
    #obs = ObservationOperator ( mu_prior['lai'] + np.random.randn(365)*0.1, 0.1, np.ones(365).astype(np.bool) )
    #cost, der_cost = obs.der_cost ( s, state_config )
    #print cost
    #print der_cost
import React, { createContext, useState, useContext, useEffect, ReactNode } from 'react';
import * as SecureStore from 'expo-secure-store';

// Helper function to normalize URLs (remove trailing slashes)
const normalizeUrl = (url: string): string => {
  return url.replace(/\/+$/, '');
};

const API_BASE_URL = normalizeUrl(process.env.EXPO_PUBLIC_API_BASE_URL || 'http://localhost:8000');
const TOKEN_KEY = 'auth_token';
const USER_KEY = 'user_data';

interface User {
  user_id: string;
  email: string;
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Load stored auth data on mount
  useEffect(() => {
    loadStoredAuth();
  }, []);

  const loadStoredAuth = async () => {
    try {
      const storedToken = await SecureStore.getItemAsync(TOKEN_KEY);
      const storedUser = await SecureStore.getItemAsync(USER_KEY);
      
      if (storedToken && storedUser) {
        setToken(storedToken);
        setUser(JSON.parse(storedUser));
      }
    } catch (error) {
      console.error('Error loading stored auth:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const login = async (email: string, password: string) => {
    try {
      const response = await fetch(`${API_BASE_URL}/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email, password }),
      });

      if (!response.ok) {
        // Try to parse JSON error response
        let errorMessage = 'Login failed';
        try {
          const errorData = await response.json();
          errorMessage = errorData.detail || errorMessage;
        } catch {
          // If JSON parsing fails, try to get text response
          try {
            const text = await response.text();
            errorMessage = text || errorMessage;
          } catch {
            // Use status-based message if all else fails
            errorMessage = `Login failed (${response.status})`;
          }
        }
        throw new Error(errorMessage);
      }

      const data = await response.json();
      const userData: User = {
        user_id: data.user_id,
        email: data.email,
      };

      // Store token and user data
      await SecureStore.setItemAsync(TOKEN_KEY, data.access_token);
      await SecureStore.setItemAsync(USER_KEY, JSON.stringify(userData));

      setToken(data.access_token);
      setUser(userData);
    } catch (error: any) {
      // Handle network errors with a user-friendly message
      if (error?.message === 'Network request failed' || error?.name === 'TypeError') {
        // Use console.warn for expected network failures (backend not running)
        console.warn('Login: Network request failed - backend may not be running');
        throw new Error('Cannot connect to server. Please check your connection and ensure the backend is running.');
      }
      console.error('Login error:', error);
      throw error;
    }
  };

  const register = async (email: string, password: string) => {
    try {
      const response = await fetch(`${API_BASE_URL}/auth/register`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email, password }),
      });

      if (!response.ok) {
        // Try to parse JSON error response
        let errorMessage = 'Registration failed';
        try {
          const errorData = await response.json();
          errorMessage = errorData.detail || errorMessage;
        } catch {
          // If JSON parsing fails, try to get text response
          try {
            const text = await response.text();
            errorMessage = text || errorMessage;
          } catch {
            // Use status-based message if all else fails
            errorMessage = `Registration failed (${response.status})`;
          }
        }
        throw new Error(errorMessage);
      }

      const data = await response.json();
      const userData: User = {
        user_id: data.user_id,
        email: data.email,
      };

      // Store token and user data
      await SecureStore.setItemAsync(TOKEN_KEY, data.access_token);
      await SecureStore.setItemAsync(USER_KEY, JSON.stringify(userData));

      setToken(data.access_token);
      setUser(userData);
    } catch (error: any) {
      // Handle network errors with a user-friendly message
      if (error?.message === 'Network request failed' || error?.name === 'TypeError') {
        // Use console.warn for expected network failures (backend not running)
        console.warn('Registration: Network request failed - backend may not be running');
        throw new Error('Cannot connect to server. Please check your connection and ensure the backend is running.');
      }
      console.error('Registration error:', error);
      throw error;
    }
  };

  const logout = async () => {
    try {
      await SecureStore.deleteItemAsync(TOKEN_KEY);
      await SecureStore.deleteItemAsync(USER_KEY);
      setToken(null);
      setUser(null);
    } catch (error) {
      console.error('Logout error:', error);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isLoading,
        login,
        register,
        logout,
        isAuthenticated: !!user && !!token,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

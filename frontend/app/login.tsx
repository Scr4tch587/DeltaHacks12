import React, { useState } from 'react';
import {
  View,
  TextInput,
  StyleSheet,
  Pressable,
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator,
  Alert,
  Text,
} from 'react-native';
import { useRouter } from 'expo-router';
import * as DocumentPicker from 'expo-document-picker';
import { Ionicons } from '@expo/vector-icons';
import { ThemedText } from '@/components/ThemedText';
import { ThemedView } from '@/components/ThemedView';
import { useAuth } from '@/contexts/AuthContext';
import { useThemeColor } from '@/hooks/use-theme-color';

export default function LoginScreen() {
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [resumeFile, setResumeFile] = useState<DocumentPicker.DocumentPickerResult | null>(null);
  const { login, register } = useAuth();
  const router = useRouter();

  const backgroundColor = useThemeColor({}, 'background');
  const textColor = useThemeColor({}, 'text');
  const tintColor = useThemeColor({}, 'tint');
  const borderColor = useThemeColor({}, 'tabIconDefault');

  const handlePickResume = async () => {
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: ['application/pdf', 'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
        copyToCacheDirectory: true,
      });
      
      if (!result.canceled) {
        setResumeFile(result);
      }
    } catch (error) {
      Alert.alert('Error', 'Failed to pick document');
    }
  };

  const handleRemoveResume = () => {
    setResumeFile(null);
  };

  const handleSubmit = async () => {
    // Validate only email and password (resume is ignored)
    if (!email.trim() || !password.trim()) {
      Alert.alert('Error', 'Please fill in all fields');
      return;
    }

    if (password.length < 6) {
      Alert.alert('Error', 'Password must be at least 6 characters');
      return;
    }

    setIsLoading(true);
    try {
      // Clear resume file before submission (resume is not sent to backend)
      if (!isLogin) {
        setResumeFile(null);
      }
      
      if (isLogin) {
        await login(email.trim(), password);
      } else {
        // Resume file is ignored - only email and password are sent
        await register(email.trim(), password);
      }
      router.replace('/(tabs)');
    } catch (error: any) {
      const errorMessage = error?.message || String(error) || 'An error occurred';
      Alert.alert('Error', errorMessage);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={[styles.container, { backgroundColor }]}
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      keyboardVerticalOffset={Platform.OS === 'ios' ? 0 : 20}
    >
      <ThemedView style={styles.content}>
        <ThemedText type="title" style={styles.title}>
          {isLogin ? 'Welcome Back' : 'Create Account'}
        </ThemedText>
        
        <ThemedText style={styles.subtitle}>
          {isLogin ? 'Sign in to continue' : 'Sign up to get started'}
        </ThemedText>

        <View style={styles.form}>
          <View style={[styles.inputContainer, { borderColor }]}>
            <TextInput
              style={[styles.input, { color: textColor }]}
              placeholder="Email"
              placeholderTextColor={borderColor}
              value={email}
              onChangeText={setEmail}
              autoCapitalize="none"
              keyboardType="email-address"
              autoComplete="email"
              editable={!isLoading}
            />
          </View>

          <View style={[styles.inputContainer, { borderColor }]}>
            <TextInput
              style={[styles.input, { color: textColor }]}
              placeholder="Password"
              placeholderTextColor={borderColor}
              value={password}
              onChangeText={setPassword}
              secureTextEntry
              autoCapitalize="none"
              autoComplete={isLogin ? 'password' : 'password-new'}
              editable={!isLoading}
            />
          </View>

          {/* Add Resume button - only shown when creating account */}
          {!isLogin && (
            <View style={styles.resumeContainer}>
              {resumeFile && !resumeFile.canceled && resumeFile.assets && resumeFile.assets[0] ? (
                <View style={[styles.resumeSelected, { borderColor }]}>
                  <View style={styles.resumeInfo}>
                    <Ionicons name="document-text" size={20} color={tintColor} />
                    <Text style={[styles.resumeFileName, { color: textColor }]} numberOfLines={1}>
                      {resumeFile.assets[0].name}
                    </Text>
                  </View>
                  <Pressable onPress={handleRemoveResume} disabled={isLoading}>
                    <Ionicons name="close-circle" size={24} color={borderColor} />
                  </Pressable>
                </View>
              ) : (
                <Pressable
                  style={[styles.resumeButton, { borderColor }, isLoading && styles.resumeButtonDisabled]}
                  onPress={handlePickResume}
                  disabled={isLoading}
                >
                  <Ionicons name="add-circle-outline" size={20} color={tintColor} />
                  <Text style={[styles.resumeButtonText, { color: tintColor }]}>
                    Add Resume
                  </Text>
                </Pressable>
              )}
            </View>
          )}

          <Pressable
            style={[styles.button, { backgroundColor: tintColor }, isLoading && styles.buttonDisabled]}
            onPress={handleSubmit}
            disabled={isLoading}
          >
            {isLoading ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <ThemedText style={styles.buttonText}>
                {isLogin ? 'Sign In' : 'Sign Up'}
              </ThemedText>
            )}
          </Pressable>

          <Pressable
            style={styles.switchButton}
            onPress={() => setIsLogin(!isLogin)}
            disabled={isLoading}
          >
            <ThemedText style={styles.switchText}>
              {isLogin
                ? "Don't have an account? Sign Up"
                : 'Already have an account? Sign In'}
            </ThemedText>
          </Pressable>
        </View>
      </ThemedView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  content: {
    flex: 1,
    justifyContent: 'center',
    padding: 20,
  },
  title: {
    marginBottom: 8,
    textAlign: 'center',
  },
  subtitle: {
    marginBottom: 32,
    textAlign: 'center',
    opacity: 0.7,
  },
  form: {
    width: '100%',
  },
  inputContainer: {
    borderWidth: 1,
    borderRadius: 8,
    marginBottom: 16,
    paddingHorizontal: 12,
    paddingVertical: 4,
  },
  input: {
    fontSize: 16,
    paddingVertical: 12,
  },
  button: {
    borderRadius: 8,
    paddingVertical: 16,
    alignItems: 'center',
    marginTop: 8,
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
  switchButton: {
    marginTop: 24,
    alignItems: 'center',
  },
  switchText: {
    fontSize: 14,
    opacity: 0.7,
  },
  resumeContainer: {
    marginBottom: 16,
  },
  resumeButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 12,
    paddingHorizontal: 16,
    gap: 8,
  },
  resumeButtonDisabled: {
    opacity: 0.6,
  },
  resumeButtonText: {
    fontSize: 16,
    fontWeight: '500',
  },
  resumeSelected: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 12,
    paddingHorizontal: 16,
  },
  resumeInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    flex: 1,
  },
  resumeFileName: {
    fontSize: 16,
    flex: 1,
  },
});

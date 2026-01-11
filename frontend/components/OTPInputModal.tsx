import React, { useState, useRef, useEffect } from 'react';
import {
  View,
  Text,
  TextInput,
  StyleSheet,
  Pressable,
  Modal,
  ViewStyle,
  TextStyle,
  Keyboard,
  Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';

interface OTPInputModalProps {
  visible: boolean;
  onCodeSubmit: (code: string) => void;
  onCancel?: () => void;
}

export const OTPInputModal: React.FC<OTPInputModalProps> = ({
  visible,
  onCodeSubmit,
  onCancel,
}) => {
  const [code, setCode] = useState('');
  const inputRef = useRef<TextInput>(null);

  // Focus input when modal becomes visible
  useEffect(() => {
    if (visible) {
      // Small delay to ensure modal is fully rendered
      setTimeout(() => {
        inputRef.current?.focus();
      }, 100);
    } else {
      // Clear code when modal closes
      setCode('');
      Keyboard.dismiss();
    }
  }, [visible]);

  const handleSubmit = () => {
    if (code.length === 8) {
      onCodeSubmit(code);
      setCode('');
    }
  };

  const handleCancel = () => {
    setCode('');
    Keyboard.dismiss();
    onCancel?.();
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={handleCancel}
    >
      <View style={styles.overlay}>
        <View style={styles.container}>
          {/* Close button */}
          {onCancel && (
            <Pressable style={styles.closeButton} onPress={handleCancel}>
              <Ionicons name="close" size={28} color="#fff" />
            </Pressable>
          )}

          {/* Title */}
          <Text style={styles.title}>Email Verification Required</Text>
          <Text style={styles.subtitle}>
            Please enter the 8-digit code sent to your email
          </Text>

          {/* OTP Input */}
          <View style={styles.inputContainer}>
            <TextInput
              ref={inputRef}
              style={styles.input}
              value={code}
              onChangeText={(text) => {
                // Only allow digits, max 8 characters
                const digitsOnly = text.replace(/[^0-9]/g, '');
                if (digitsOnly.length <= 8) {
                  setCode(digitsOnly);
                }
              }}
              placeholder="00000000"
              placeholderTextColor="rgba(255, 255, 255, 0.3)"
              keyboardType="number-pad"
              maxLength={8}
              selectTextOnFocus
              autoFocus
            />
            <Text style={styles.inputHint}>
              {code.length}/8 digits
            </Text>
          </View>

          {/* Submit button */}
          <Pressable
            style={[
              styles.submitButton,
              code.length === 8 && styles.submitButtonActive,
            ]}
            onPress={handleSubmit}
            disabled={code.length !== 8}
          >
            <Text
              style={[
                styles.submitButtonText,
                code.length !== 8 && styles.submitButtonTextDisabled,
              ]}
            >
              Verify
            </Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.85)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  } as ViewStyle,

  container: {
    backgroundColor: 'rgba(20, 20, 20, 0.95)',
    borderRadius: 24,
    padding: 32,
    width: '100%',
    maxWidth: 400,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.1)',
  } as ViewStyle,

  closeButton: {
    position: 'absolute',
    top: 16,
    right: 16,
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(255, 255, 255, 0.1)',
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 1,
  } as ViewStyle,

  title: {
    color: '#fff',
    fontSize: 24,
    fontWeight: '700',
    marginBottom: 8,
    textAlign: 'center',
  } as TextStyle,

  subtitle: {
    color: 'rgba(255, 255, 255, 0.7)',
    fontSize: 16,
    marginBottom: 32,
    textAlign: 'center',
    lineHeight: 22,
  } as TextStyle,

  inputContainer: {
    width: '100%',
    marginBottom: 24,
    alignItems: 'center',
  } as ViewStyle,

  input: {
    width: '100%',
    height: 80,
    backgroundColor: 'rgba(255, 255, 255, 0.1)',
    borderRadius: 16,
    borderWidth: 2,
    borderColor: 'rgba(255, 255, 255, 0.2)',
    color: '#fff',
    fontSize: 36,
    fontWeight: '700',
    textAlign: 'center',
    letterSpacing: 8,
    paddingHorizontal: 20,
    ...Platform.select({
      ios: {
        fontVariant: ['tabular-nums'],
      },
      android: {
        fontFamily: 'monospace',
      },
    }),
  } as TextStyle,

  inputHint: {
    color: 'rgba(255, 255, 255, 0.5)',
    fontSize: 14,
    marginTop: 8,
    fontWeight: '500',
  } as TextStyle,

  submitButton: {
    width: '100%',
    height: 56,
    backgroundColor: 'rgba(255, 255, 255, 0.2)',
    borderRadius: 16,
    justifyContent: 'center',
    alignItems: 'center',
  } as ViewStyle,

  submitButtonActive: {
    backgroundColor: '#007AFF',
  } as ViewStyle,

  submitButtonText: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '700',
  } as TextStyle,

  submitButtonTextDisabled: {
    color: 'rgba(255, 255, 255, 0.5)',
  } as TextStyle,
});
